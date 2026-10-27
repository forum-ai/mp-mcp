"""Objects the REST endpoints do not return directly: band structures, densities of states,
phonons, phase diagrams, entries, Wulff shapes and the rest. They come from the get_*
methods of the installed mp-api client, found by introspection, so they track mp-api.

Each result goes back in one of these forms:
  summary  a few lines a person can read, plus a plot where pymatgen has one
  json     the full pymatgen object as JSON (as_dict), for agents that load it with
           monty.serialization.loadfn; large ones go to a file or a download link
  cif, poscar  a Structure as a text file format (structures only)
"""
from __future__ import annotations

import hashlib
import inspect
import io
import json
import os
import secrets
import time
import warnings
from functools import cache
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from monty.json import MontyEncoder

INLINE_LIMIT = int(os.environ.get("MP_MCP_INLINE_BYTES", 50_000))
LINK_TTL = int(os.environ.get("MP_MCP_LINK_TTL", 3600))
MAX_OBJECT_BYTES = int(os.environ.get("MP_MCP_MAX_OBJECT_BYTES", 50_000_000))
STORE_BYTES = int(os.environ.get("MP_MCP_STORE_BYTES", 256_000_000))
SKIP = {"get_data_by_id", "get_database_version", "get_emmet_version", "get_download_info"}
STRUCTURE_FORMATS = ("cif", "poscar")
LIST_ROWS = 50  # rows shown when summarizing a list of objects


class TooLarge(Exception):
    pass


# ---------------------------------------------------------------- the client and its methods
def _client(api_key: str, offline: bool = False):
    """An MPRester. MPRester.__init__ calls the API's /heartbeat twice (cached per process);
    with offline=True those calls are skipped, so the route tree can be walked with no network."""
    from mp_api.client import MPRester
    from mp_api.client.core.client import BaseRester

    if not offline:
        return MPRester(api_key=api_key, mute_progress_bars=True)
    with mock.patch.object(MPRester, "get_emmet_version", staticmethod(lambda endpoint: None)), \
         mock.patch.object(BaseRester, "_get_heartbeat_info", staticmethod(lambda endpoint: (None, []))):
        return MPRester(api_key=api_key, mute_progress_bars=True)


def _getters(obj: Any, prefix: str = "") -> dict[str, Callable]:
    """The public get_* methods of one object, bound, by (prefixed) name."""
    return {f"{prefix}{n}": getattr(obj, n) for n in dir(obj) if n.startswith("get_") and n not in SKIP}


def discover() -> dict[str, Callable]:
    """Every public get_* method on MPRester and on each route under it, by dotted name.
    Needs no network: the client is built offline, only to walk its route tree."""
    with warnings.catch_warnings():  # mp-api's own deprecation and legacy-route notices while walking
        warnings.simplefilter("ignore")
        mpr = _client("x" * 32, offline=True)
        found = _getters(mpr)
        for group in ("materials", "molecules"):
            g = getattr(mpr, group, None)
            for route in dir(g) if g is not None else []:
                try:
                    r = getattr(g, route)  # routes are built lazily here, and some warn
                except Exception:
                    continue
                if not route.startswith("_") and hasattr(r, "search"):
                    found |= _getters(r, f"{group}.{route}.")
    return found


def _first_line(fn: Callable) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.strip().split("\n\n")[0].replace("\n", " ")


def describe(found: dict[str, Callable], search: str = "") -> str:
    s = search.lower()
    lines = []
    for name, fn in sorted(found.items()):
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = "(...)"
        line = f"{name}{sig}  {_first_line(fn)}"
        if s in line.lower():
            lines.append(line)
    return "\n".join(lines) or f"No methods match {search!r}."


def call(api_key: str, method: str, args: dict[str, Any]) -> Any:
    with _client(api_key) as mpr:
        target: Any = mpr
        for part in method.split("."):
            target = getattr(target, part)
        return unwrap(target(**args))


def unwrap(obj: Any) -> Any:
    """mp-api returns some objects as emmet-core models (PhononBS, PhononDOS) that carry the
    pymatgen object under to_pmg (a cached property, or a method). Use the pymatgen one."""
    pmg = getattr(obj, "to_pmg", None)
    if pmg is None:
        return obj
    try:
        return pmg() if callable(pmg) else pmg
    except Exception:
        return obj


# ---------------------------------------------------------------- summaries
def _png(plot: Callable[[], Any]) -> bytes | None:
    """Run a pymatgen plotter and return its figure as PNG, or None if it fails. Plotters
    return either an Axes (which has .figure) or a Figure."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        drawn = plot()
        fig = getattr(drawn, "figure", drawn)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def _band_structure(bs) -> str:
    gap = bs.get_band_gap()
    what = f"Band structure of {bs.structure.composition.reduced_formula}" if bs.structure is not None else "Band structure"
    return (f"{what}\nband gap: {gap['energy']:.3f} eV, {'direct' if gap['direct'] else 'indirect'}, "
            f"transition {gap['transition']}\nmetal: {bs.is_metal()}; Fermi level {bs.efermi:.3f} eV")


def _dos_plot(dos):
    from pymatgen.electronic_structure.plotter import DosPlotter

    p = DosPlotter()
    p.add_dos("Total", dos)
    if hasattr(dos, "get_element_dos"):
        p.add_dos_dict({str(k): v for k, v in dos.get_element_dos().items()})
    return p.get_plot(xlim=(-8, 8))


def _phonon_dos(dos) -> str:
    rows = [f"T = {t} K: Cv {dos.cv(t):.3f} J/(K mol), S {dos.entropy(t):.3f} J/(K mol), "
            f"F {dos.helmholtz_free_energy(t) / 1000:.3f} kJ/mol" for t in (100, 300, 600, 1000)]
    return "Phonon DOS\n" + "\n".join(rows)


def _phonon_dos_plot(dos):
    from pymatgen.phonon.plotter import PhononDosPlotter

    p = PhononDosPlotter()
    p.add_dos("Total", dos)
    return p.get_plot()


def _phase_diagram(pd) -> str:
    stable = sorted(pd.stable_entries, key=lambda e: e.composition.reduced_formula)
    lines = [f"Phase diagram of {'-'.join(sorted(map(str, pd.elements)))}: {len(stable)} stable phases"]
    lines += [f"  {e.composition.reduced_formula} ({getattr(e, 'entry_id', None) or 'no id'}): formation energy "
              f"{pd.get_form_energy_per_atom(e):.3f} eV/atom" for e in stable]
    return "\n".join(lines)


def _structure(s) -> str:
    a, b, c = s.lattice.abc
    return (f"{s.composition.reduced_formula}, {s.get_space_group_info()[0]}, {len(s)} sites; "
            f"a={a:.4f} b={b:.4f} c={c:.4f} Å; density {s.density:.3f} g/cm3. "
            "Ask for format cif, poscar or json for the full structure.")


def _volumetric(v) -> str:  # Chgcar and friends: never serialize the grid for a summary
    s = v.structure
    return (f"{type(v).__name__} for {s.composition.reduced_formula} ({len(s)} sites): grid {'x'.join(map(str, v.dim))}, "
            f"{len(v.data)} data set(s) ({', '.join(v.data)}). Ask for json to get the whole grid; it is large.")


def _wulff(w) -> str:  # WulffShape.structure is a one-atom placeholder, so no formula here
    facets = sorted(w.miller_energy_dict.items(), key=lambda kv: -w.area_fraction_dict.get(kv[0], 0))
    lines = [f"Wulff shape: weighted surface energy {w.weighted_surface_energy:.3f} J/m2, "
             f"anisotropy {w.anisotropy:.3f}, shape factor {w.shape_factor:.3f}",
             "  facet  surface energy (J/m2)  area fraction"]
    lines += [f"  {''.join(map(str, hkl)):>5}  {e:21.3f}  {w.area_fraction_dict.get(hkl, 0):13.3f}" for hkl, e in facets]
    return "\n".join(lines)


@cache
def _summaries() -> list[tuple[type, Callable[[Any], str], Callable[[Any], Any] | None]]:
    """(type, text, plot) for each object type with a hand-written summary, in match order.
    Imported once, on first use, since pymatgen is slow to import."""
    from pymatgen.analysis.phase_diagram import PDPlotter, PhaseDiagram
    from pymatgen.analysis.wulff import WulffShape
    from pymatgen.core import Structure
    from pymatgen.electronic_structure.bandstructure import BandStructure
    from pymatgen.electronic_structure.dos import Dos
    from pymatgen.electronic_structure.plotter import BSPlotter
    from pymatgen.io.common import VolumetricData
    from pymatgen.phonon.bandstructure import PhononBandStructureSymmLine
    from pymatgen.phonon.dos import PhononDos
    from pymatgen.phonon.plotter import PhononBSPlotter

    return [
        (BandStructure, _band_structure, lambda o: BSPlotter(o).get_plot()),
        (Dos, lambda o: f"Density of states; gap {o.get_gap():.3f} eV; Fermi level {o.efermi:.3f} eV", _dos_plot),
        (PhononBandStructureSymmLine,
         lambda o: (f"Phonon band structure; lowest frequency {float(o.bands.min()):.3f} THz; "
                    f"imaginary modes: {o.has_imaginary_freq()}; highest {float(o.bands.max()):.2f} THz"),
         lambda o: PhononBSPlotter(o).get_plot()),
        (PhononDos, _phonon_dos, _phonon_dos_plot),
        (PhaseDiagram, _phase_diagram, lambda o: PDPlotter(o, backend="matplotlib").get_plot()),
        (Structure, _structure, None),
        (VolumetricData, _volumetric, None),
        (WulffShape, _wulff, lambda o: o.get_plot()),
    ]


@cache
def _rows() -> list[tuple[type, str, Callable[[Any], str]]]:
    """(type, what to call them, one-line row) for lists of objects."""
    from pymatgen.analysis.pourbaix_diagram import PourbaixEntry
    from pymatgen.entries.computed_entries import ComputedEntry

    return [
        (PourbaixEntry, "Pourbaix entries (solids and aqueous ions; build the diagram with "
                        "pymatgen.analysis.pourbaix_diagram.PourbaixDiagram from the json)",
         lambda e: (f"{str(e.entry_id or '-'):>14}  {str(e.name):>22}  E {float(e.energy):8.3f} eV  "
                    f"npH {float(e.npH):5.1f}  nPhi {float(e.nPhi):5.1f}  nH2O {float(e.nH2O):5.1f}")),
        (ComputedEntry, "entries", lambda e: f"{e.entry_id}  {e.composition.reduced_formula}  {e.energy_per_atom:.4f} eV/atom"),
    ]


def summarize(obj: Any) -> tuple[str, bytes | None]:
    """A few readable lines about the object, plus a PNG plot where pymatgen draws one."""
    for cls, text, plot in _summaries():
        if isinstance(obj, cls):
            return text(obj), _png(lambda: plot(obj)) if plot else None
    if isinstance(obj, list) and obj:
        for cls, what, row in _rows():
            if all(isinstance(e, cls) for e in obj):
                lines = [f"{len(obj)} {what}"] + [f"  {row(e)}" for e in obj[:LIST_ROWS]]
                if len(obj) > LIST_ROWS:
                    lines.append(f"  ... {len(obj) - LIST_ROWS} more; ask for json for all")
                return "\n".join(lines), None
    text = json.dumps(obj, cls=MontyEncoder, default=str)
    if len(text) > 4000:
        text = text[:4000] + f"... [{len(text):,} characters in all; ask for json]"
    return f"{type(obj).__name__}: {text}", None


def structure_text(obj: Any, fmt: str) -> str:
    """A Structure, or a list of them, as cif or poscar text."""
    from pymatgen.core import Structure

    structures = obj if isinstance(obj, list) else [obj]
    if not structures or not all(isinstance(s, Structure) for s in structures):
        raise TypeError(f"format {fmt} is only for structures; this method returned a {type(obj).__name__}. Use summary or json.")
    if len(structures) == 1:
        return structures[0].to(fmt=fmt)
    return "\n\n".join(f"# structure {i + 1} of {len(structures)}\n{s.to(fmt=fmt)}" for i, s in enumerate(structures))


# ---------------------------------------------------------------- full JSON
class Store:
    """Large JSON results: a file next to the user (local) or a short-lived link (hosted).
    Holds at most STORE_BYTES in memory; the oldest links go first when it is full."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, bytes, str]] = {}

    def put(self, data: bytes, name: str) -> str:
        now = time.time()
        self._items = {k: v for k, v in self._items.items() if v[0] > now}
        held = sum(len(v[1]) for v in self._items.values())
        for token in sorted(self._items, key=lambda k: self._items[k][0]):  # oldest first
            if held + len(data) <= STORE_BYTES:
                break
            held -= len(self._items.pop(token)[1])
        token = secrets.token_urlsafe(24)
        self._items[token] = (now + LINK_TTL, data, name)
        return token

    def get(self, token: str) -> tuple[bytes, str] | None:
        item = self._items.get(token)
        if item and item[0] > time.time():
            return item[1], item[2]
        return None


def to_json(obj: Any) -> bytes:
    data = json.dumps(obj, cls=MontyEncoder).encode()
    if len(data) > MAX_OBJECT_BYTES:
        raise TooLarge(f"{len(data):,} bytes of JSON; this server returns at most {MAX_OBJECT_BYTES:,}. "
                       "Fetch this object with mp-api directly, or ask for the summary.")
    return data


def output_dir() -> Path:
    """Where a local (stdio) server writes large objects: MP_MCP_OUTPUT_DIR, else a cache folder
    in the user's home, never the current directory (which is whatever project the client opened)."""
    if env := os.environ.get("MP_MCP_OUTPUT_DIR"):
        return Path(env).expanduser().resolve()
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return (base / "mp-mcp" / "objects").resolve()


def local_file(data: bytes, method: str, args: dict[str, Any]) -> Path:
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:10]
    path = out / f"{method.replace('.', '_')}_{tag}.json"
    path.write_bytes(data)
    return path
