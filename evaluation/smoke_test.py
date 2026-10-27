"""Live smoke test: every tool of the server against the real Materials Project API.

Builds the server in this process (live spec, docs tools on), connects to it as an MCP client
and runs the requests a materials scientist would make, one per line. Needs MP_API_KEY in the
environment (or PMG_MAPI_KEY in ~/.config/.pmgrc.yaml). Writes nothing. Exit code 1 if any
request fails.

    export MP_API_KEY=...
    uv run evaluation/smoke_test.py            # all
    uv run evaluation/smoke_test.py phonon     # only requests whose name contains "phonon"
"""

import asyncio
import json
import logging
import os
import sys
import time
import warnings

from fastmcp import Client

from mp_mcp.server import build_server

# Four cases send bad input on purpose; fastmcp logs each refused call at ERROR level, and
# matplotlib comments on the phase-diagram plot. Neither is a result, so keep them out.
logging.getLogger("fastmcp").setLevel(logging.CRITICAL)
logging.getLogger("FastMCP").setLevel(logging.CRITICAL)
logging.getLogger("matplotlib").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

ONLY = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
results = []

SI_STRUCTURE = {"@module": "pymatgen.core.structure", "@class": "Structure", "lattice": {"matrix": [[0, 2.7, 2.7], [2.7, 0, 2.7], [2.7, 2.7, 0]]},
                "sites": [{"species": [{"element": "Si", "occu": 1}], "abc": [0, 0, 0]}, {"species": [{"element": "Si", "occu": 1}], "abc": [0.25, 0.25, 0.25]}]}

# (name, tool, arguments, check)  check: a function of the text result, or a substring
CASES = [
    ("list endpoints", "list_endpoints", {}, "/materials/summary/"),
    ("describe summary, gap filters", "describe_endpoint", {"path": "/materials/summary/", "search": "gap"}, "band_gap_min"),
    ("describe synthesis (no field docs)", "describe_endpoint", {"path": "/materials/synthesis/"}, "not described"),
    ("property by mp-id", "query", {"path": "/materials/summary/", "fields": ["material_id", "band_gap", "energy_above_hull"], "params": {"material_ids": "mp-149"}}, "mp-149"),
    ("several mp-ids as a list", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty"], "params": {"material_ids": ["mp-149", "mp-2534"]}}, "mp-2534"),
    ("polymorphs of a formula", "query", {"path": "/materials/summary/", "fields": ["material_id", "symmetry", "energy_above_hull"], "params": {"formula": "NaFePO4"}, "limit": 50}, "energy_above_hull"),
    ("stable phases in a chemsys", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty"], "params": {"chemsys": "Li-Fe-O", "is_stable": True}, "limit": 50}, lambda t: "LiFeO2" in t or "Fe" in t),
    ("range screen (Ba ternary oxides, 2-3 eV)", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty", "band_gap"], "params": {"elements": "Ba,O", "nelements": 3, "is_stable": True, "band_gap_min": 2, "band_gap_max": 3}, "limit": 10}, lambda t: int(t.split()[0]) > 5),
    ("count only (limit=1)", "query", {"path": "/materials/summary/", "fields": ["material_id"], "params": {"elements": "Li,O", "is_stable": True}, "limit": 1}, lambda t: int(t.split()[0]) > 50 and "1 returned" in t),
    ("paging with _skip", "query", {"path": "/materials/summary/", "fields": ["material_id"], "params": {"chemsys": "Li-O", "_skip": 2}, "limit": 2}, "2 returned"),
    ("sort descending on summary", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty", "k_vrh"], "params": {"elements": "O", "nelements": 2, "is_stable": True, "k_vrh_min": 0}, "sort": "-k_vrh", "limit": 5},
     lambda t: (lambda ks: ks == sorted(ks, reverse=True) and len(ks) == 5)([r.get("k_vrh") or -1 for r in json.loads(t.split("\n", 1)[1])])),
    ("sort on an endpoint without sorting is refused", "query", {"path": "/materials/elasticity/", "fields": ["material_id"], "sort": "-k_vrh"}, "ERROR:does not support sorting"),
    ("decomposition products", "query", {"path": "/materials/summary/", "fields": ["material_id", "energy_above_hull", "decomposes_to"], "params": {"formula": "Li7P3S11"}}, "decomposes_to"),
    ("space group filter", "query", {"path": "/materials/summary/", "fields": ["material_id", "symmetry"], "params": {"formula": "LiCoO2", "spacegroup_symbol": "R-3m"}}, "R-3m"),
    ("wildcard formula", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty"], "params": {"formula": "ABO3", "is_stable": True}, "limit": 5}, "5 returned"),
    ("exclude elements", "query", {"path": "/materials/summary/", "fields": ["material_id", "formula_pretty"], "params": {"elements": "Li,Mn", "exclude_elements": "O", "is_stable": True}, "limit": 5}, lambda t: "O" not in "".join(r["formula_pretty"] for r in json.loads(t.split("\n", 1)[1]))),
    ("has_props phonon", "query", {"path": "/materials/summary/", "fields": ["material_id", "has_props"], "params": {"has_props": "phonon", "material_ids": "mp-149"}}, "1 matches"),
    ("thermo endpoint, one functional", "query", {"path": "/materials/thermo/", "fields": ["material_id", "thermo_type", "energy_above_hull"], "params": {"material_ids": "mp-149", "thermo_types": "GGA_GGA+U_R2SCAN"}}, "GGA_GGA+U_R2SCAN"),
    ("elasticity document", "query", {"path": "/materials/elasticity/", "fields": ["material_id", "bulk_modulus", "shear_modulus"], "params": {"material_ids": "mp-149"}}, "bulk_modulus"),
    ("dielectric document", "query", {"path": "/materials/dielectric/", "fields": ["material_id", "e_total", "n"], "params": {"material_ids": "mp-2657"}}, "e_total"),
    ("magnetism document", "query", {"path": "/materials/magnetism/", "fields": ["material_id", "ordering", "total_magnetization"], "params": {"material_ids": "mp-19306"}}, "ordering"),
    ("insertion electrodes", "query", {"path": "/materials/insertion_electrodes/", "fields": ["battery_id", "formula_discharge", "average_voltage", "capacity_grav"], "params": {"working_ion": "Li", "elements": "Fe,P,O"}, "limit": 10}, "average_voltage"),
    ("surface properties", "query", {"path": "/materials/surface_properties/", "fields": ["material_id", "weighted_surface_energy", "weighted_work_function"], "params": {"material_ids": "mp-149"}}, "weighted_surface_energy"),
    ("provenance / database ids", "query", {"path": "/materials/provenance/", "fields": ["material_id", "database_IDs", "theoretical"], "params": {"material_ids": "mp-149"}}, "database_IDs"),
    ("robocrys description", "query", {"path": "/materials/robocrys/", "fields": ["material_id", "description"], "params": {"material_ids": "mp-149"}}, "description"),
    ("xas spectra", "query", {"path": "/materials/xas/", "fields": ["material_id", "edge", "absorbing_element"], "params": {"formula": "Si", "edge": "K"}, "limit": 3}, "absorbing_element"),
    ("synthesis recipes (no fields)", "query", {"path": "/materials/synthesis/", "params": {"target_formula": "LiFePO4"}, "limit": 2}, lambda t: "doi" in t.lower()),
    ("formula autocomplete (limit, no _limit)", "query", {"path": "/materials/core/formula_autocomplete/", "params": {"formula": "LiFePO"}, "limit": 5}, lambda t: "LiFePO4" in t),
    ("find structure (POST, ids stay alpha: no id_format there)", "query", {"path": "/materials/core/find_structure/", "body": SI_STRUCTURE}, lambda t: "mp-149" in t or "mp-aaaaaaft" in t),
    ("molecules summary", "query", {"path": "/molecules/summary/", "fields": ["molecule_id", "formula_alphabetical", "charge"], "params": {"elements": "C,H", "nelements": 2, "charge": 0}, "limit": 3}, "molecule_id"),
    ("tasks", "query", {"path": "/materials/tasks/", "fields": ["task_id", "run_type"], "params": {"task_ids": "mp-149"}}, "run_type"),
    ("list objects", "list_objects", {"search": "phonon"}, "get_phonon_bandstructure_by_material_id"),
    ("structure summary", "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}}, "Fd-3m"),
    ("structure as CIF, conventional cell", "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149", "conventional_unit_cell": True}, "format": "cif"}, "_cell_length_a"),
    ("structure as POSCAR", "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}, "format": "poscar"}, "Si"),
    ("structure as JSON", "get_object", {"method": "get_structure_by_material_id", "args": {"material_id": "mp-149"}, "format": "json"}, '"@class": "Structure"'),
    ("band structure summary + plot", "get_object", {"method": "get_bandstructure_by_material_id", "args": {"material_id": "mp-149"}}, "IMAGE:band gap"),
    ("DOS summary + plot", "get_object", {"method": "get_dos_by_material_id", "args": {"material_id": "mp-149"}}, "IMAGE:Density of states"),
    ("phonon band structure", "get_object", {"method": "get_phonon_bandstructure_by_material_id", "args": {"material_id": "mp-149"}}, "imaginary modes"),
    ("phonon DOS", "get_object", {"method": "get_phonon_dos_by_material_id", "args": {"material_id": "mp-149"}}, "Phonon DOS"),
    ("phase diagram", "get_object", {"method": "materials.thermo.get_phase_diagram_from_chemsys", "args": {"chemsys": "Fe-Li-O"}}, "stable phases"),
    ("entries in chemsys", "get_object", {"method": "get_entries_in_chemsys", "args": {"elements": "Li-O"}}, "entries"),
    ("pourbaix entries", "get_object", {"method": "get_pourbaix_entries", "args": {"chemsys": "Zn"}}, "Pourbaix entries"),
    ("wulff shape + plot", "get_object", {"method": "get_wulff_shape", "args": {"material_id": "mp-149"}}, "IMAGE:Wulff shape"),
    ("bad method name", "get_object", {"method": "get_everything"}, "ERROR:No method"),
    ("bad kwarg", "get_object", {"method": "get_structure_by_material_id", "args": {"mpid": "mp-149"}}, "ERROR:Bad arguments"),
    ("unknown endpoint", "query", {"path": "/materials/nothing/", "fields": ["x"]}, "ERROR:No endpoint"),
    ("docs search", "docs_search", {"query": "energy above hull"}, "docs.materialsproject.org"),
    ("docs page", "docs_page", {"url": "https://docs.materialsproject.org/methodology/materials-methodology/thermodynamic-stability"}, lambda t: len(t) > 500),
]


async def run_case(c, name, tool, args, check):
    t0 = time.time()
    try:
        r = await c.call_tool(tool, args, raise_on_error=False)
        texts = [b.text for b in r.content if getattr(b, "type", "") == "text"]
        has_image = any(getattr(b, "type", "") == "image" for b in r.content)
        text = "\n".join(texts)
        if r.is_error:
            ok = isinstance(check, str) and check.startswith("ERROR:") and check[6:] in text
        elif isinstance(check, str) and check.startswith("ERROR:"):
            ok = False
        elif isinstance(check, str) and check.startswith("IMAGE:"):
            ok = has_image and check[6:] in text
        elif isinstance(check, str):
            ok = check in text
        else:
            ok = bool(check(text))
        note = text.replace("\n", " ")[:110]
    except Exception as exc:
        ok, note = False, f"{type(exc).__name__}: {exc}"[:160]
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {time.time() - t0:5.1f}s  {name:48s} {note}")


async def main():
    mcp = build_server()
    async with Client(mcp) as c:
        for name, tool, args, check in CASES:
            if ONLY in name.lower():
                await run_case(c, name, tool, args, check)
    print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
