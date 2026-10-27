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


class TooLarge(Exception):
    pass


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


def _first_line(fn: Callable) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.strip().split("\n\n")[0].replace("\n", " ")


def discover() -> dict[str, Callable]:
    """Every public get_* method on MPRester and on each route under it, by dotted name.
    Needs no network: the client is built offline, only to walk its route tree."""
    with warnings.catch_warnings():  # mp-api's own deprecation and legacy-route notices while walking
        warnings.simplefilter("ignore")
        mpr = _client("x" * 32, offline=True)
    found: dict[str, Callable] = {}
    for name in dir(mpr):
        if name.startswith("get_") and name not in SKIP:
            found[name] = getattr(type(mpr), name)
    for group in ("materials", "molecules"):
        g = getattr(mpr, group, None)
        for route in dir(g) if g is not None else []:
            if route.startswith("_"):
                continue
            try:
                r = getattr(g, route)
            except Exception:
                continue
            if not hasattr(r, "search"):
                continue
            for name in dir(r):
                if name.startswith("get_") and name not in SKIP:
                    found[f"{group}.{route}.{name}"] = getattr(r, name)
    return found


def describe(found: dict[str, Callable], search: str = "") -> str:
    s = search.lower()
    lines = []
    for name, fn in sorted(found.items()):
        try:
            sig = str(inspect.signature(fn)).replace("(self, ", "(").replace("(self)", "()")
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
def _png(fig_or_ax) -> bytes | None:
    try:
        fig = getattr(fig_or_ax, "figure", None) or getattr(fig_or_ax, "get_figure", lambda: fig_or_ax)()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        import matplotlib.pyplot as plt

        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def summarize(obj: Any) -> tuple[str, bytes | None]:
    import matplotlib

    matplotlib.use("Agg")
    from pymatgen.analysis.phase_diagram import PhaseDiagram
    from pymatgen.core import Structure
    from pymatgen.electronic_structure.bandstructure import BandStructure
    from pymatgen.electronic_structure.dos import Dos
    from pymatgen.entries.computed_entries import ComputedEntry
    from pymatgen.io.common import VolumetricData
    from pymatgen.phonon.bandstructure import PhononBandStructureSymmLine
    from pymatgen.phonon.dos import PhononDos

    if isinstance(obj, BandStructure):
        gap = obj.get_band_gap()
        what = f"Band structure of {obj.structure.composition.reduced_formula}" if obj.structure is not None else "Band structure"
        lines = [what,
                 f"band gap: {gap['energy']:.3f} eV, {'direct' if gap['direct'] else 'indirect'}, transition {gap['transition']}",
                 f"metal: {obj.is_metal()}; Fermi level {obj.efermi:.3f} eV"]
        try:
            from pymatgen.electronic_structure.plotter import BSPlotter

            return "\n".join(lines), _png(BSPlotter(obj).get_plot())
        except Exception:
            return "\n".join(lines), None
    if isinstance(obj, Dos):
        lines = [f"Density of states; gap {obj.get_gap():.3f} eV; Fermi level {obj.efermi:.3f} eV"]
        try:
            from pymatgen.electronic_structure.plotter import DosPlotter

            p = DosPlotter()
            p.add_dos("Total", obj)
            if hasattr(obj, "get_element_dos"):
                p.add_dos_dict({str(k): v for k, v in obj.get_element_dos().items()})
            return "\n".join(lines), _png(p.get_plot(xlim=(-8, 8)))
        except Exception:
            return "\n".join(lines), None
    if isinstance(obj, PhononBandStructureSymmLine):
        fmin = float(obj.bands.min())
        lines = [f"Phonon band structure; lowest frequency {fmin:.3f} THz; "
                 f"imaginary modes: {obj.has_imaginary_freq()}; highest {float(obj.bands.max()):.2f} THz"]
        try:
            from pymatgen.phonon.plotter import PhononBSPlotter

            return "\n".join(lines), _png(PhononBSPlotter(obj).get_plot())
        except Exception:
            return "\n".join(lines), None
    if isinstance(obj, PhononDos):
        rows = [f"T = {t} K: Cv {obj.cv(t):.3f} J/(K mol), S {obj.entropy(t):.3f} J/(K mol), "
                f"F {obj.helmholtz_free_energy(t) / 1000:.3f} kJ/mol" for t in (100, 300, 600, 1000)]
        try:
            from pymatgen.phonon.plotter import PhononDosPlotter

            p = PhononDosPlotter()
            p.add_dos("Total", obj)
            return "Phonon DOS\n" + "\n".join(rows), _png(p.get_plot())
        except Exception:
            return "Phonon DOS\n" + "\n".join(rows), None
    if isinstance(obj, PhaseDiagram):
        stable = sorted(obj.stable_entries, key=lambda e: e.composition.reduced_formula)
        lines = [f"Phase diagram of {'-'.join(sorted(map(str, obj.elements)))}: {len(stable)} stable phases"]
        lines += [f"  {e.composition.reduced_formula} ({getattr(e, 'entry_id', None) or 'no id'}): formation energy "
                  f"{obj.get_form_energy_per_atom(e):.3f} eV/atom" for e in stable]
        try:
            from pymatgen.analysis.phase_diagram import PDPlotter

            return "\n".join(lines), _png(PDPlotter(obj, backend="matplotlib").get_plot())
        except Exception:
            return "\n".join(lines), None
    if isinstance(obj, Structure):
        a, b, c = obj.lattice.abc
        return (f"{obj.composition.reduced_formula}, {obj.get_space_group_info()[0]}, {len(obj)} sites; "
                f"a={a:.4f} b={b:.4f} c={c:.4f} Å; density {obj.density:.3f} g/cm3. "
                "Ask for format cif, poscar or json for the full structure."), None
    if isinstance(obj, VolumetricData):  # Chgcar and friends: never serialize the grid for a summary
        s = obj.structure
        return (f"{type(obj).__name__} for {s.composition.reduced_formula} ({len(s)} sites): grid {'x'.join(map(str, obj.dim))}, "
                f"{len(obj.data)} data set(s) ({', '.join(obj.data)}). Ask for json to get the whole grid; it is large."), None
    if isinstance(obj, list) and obj and all(isinstance(e, ComputedEntry) for e in obj):
        rows = [f"  {e.entry_id}  {e.composition.reduced_formula}  {e.energy_per_atom:.4f} eV/atom" for e in obj[:50]]
        more = f"\n  ... {len(obj) - 50} more; ask for json for all" if len(obj) > 50 else ""
        return f"{len(obj)} entries\n" + "\n".join(rows) + more, None
    text = json.dumps(obj, cls=MontyEncoder, default=str)
    if len(text) > 4000:
        text = text[:4000] + f"... [{len(text):,} characters in all; ask for json]"
    return f"{type(obj).__name__}: {text}", None


def structure_text(obj: Any, fmt: str) -> str:
    """A Structure (or a list of them) as cif or poscar text."""
    from pymatgen.core import Structure

    if isinstance(obj, list) and obj and all(isinstance(s, Structure) for s in obj):
        return "\n\n".join(f"# structure {i + 1} of {len(obj)}\n{s.to(fmt=fmt)}" for i, s in enumerate(obj))
    if not isinstance(obj, Structure):
        raise TypeError(f"format {fmt} is only for structures; this method returned a {type(obj).__name__}. Use summary or json.")
    return obj.to(fmt=fmt)


# ---------------------------------------------------------------- full JSON
class Store:
    """Large JSON results: a file next to the user (local) or a short-lived link (hosted).
    Holds at most STORE_BYTES in memory; the oldest links go first when it is full."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, bytes, str]] = {}

    def _bytes(self) -> int:
        return sum(len(v[1]) for v in self._items.values())

    def put(self, data: bytes, name: str) -> str:
        now = time.time()
        self._items = {k: v for k, v in self._items.items() if v[0] > now}
        while self._items and self._bytes() + len(data) > STORE_BYTES:
            del self._items[min(self._items, key=lambda k: self._items[k][0])]
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
