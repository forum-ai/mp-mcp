---
name: materials-project
description: Answer questions about inorganic materials and molecules from the Materials Project (MP) through the materials-project MCP tools. Use whenever a question touches stability or energy above hull, band gaps and band structures, crystal structures and polymorphs, phonons, elastic, dielectric, piezoelectric or magnetic properties, battery electrodes, surfaces, synthesis recipes, phase diagrams, similar materials, or names an mp-id, even when MP is not mentioned. Use the tools, never an mp-api script.
---

# Materials Project through the MCP tools

The `materials-project` server exposes every MP REST endpoint and every `mp-api` object method as seven tools. Use them for any MP data. Do not `pip install mp-api`, write a Python script, or fetch the REST API yourself: what would be a script with an environment, a key file and an install step is one `query` call here. If the tools are not visible, say so instead of working around them.

## The routine

1. `list_endpoints` once, then `describe_endpoint(path, search)` for the endpoint you need, with `search` set to the property word (`"gap"`, `"hull"`, `"modulus"`). It returns the exact filter names and field names; never guess them.
2. `query(path, fields, params, limit, sort)` with the few fields you need and a small `limit`. The first line of the result is the total number of matches.
3. For an object (band structure, DOS, phonons, phase diagram, structure file), `list_objects(search)` then `get_object(method, args, format)`.
4. For how MP computes something, `docs_search(query)`.

## Which call answers what

| Question | Call |
|---|---|
| A property of a known material | `query("/materials/summary/", fields=[...], params={"material_ids": "mp-149"})` |
| Every polymorph of a formula, with stability | `query("/materials/summary/", fields=["material_id","symmetry","energy_above_hull"], params={"formula": "NaFePO4"}, limit=50)`; lowest `energy_above_hull` is MP's ground state |
| Stable phases in a chemical system | `params={"chemsys": "Li-Fe-O", "is_stable": True}` |
| A screen by property ranges | `params={"elements": "Ba,O", "nelements": 3, "is_stable": True, "band_gap_min": 2, "band_gap_max": 3}`; ranges are `<field>_min` / `<field>_max` |
| How many materials satisfy a filter | the same `query` with `limit=1`; read the total on the first line |
| A ranked list ("ten highest bulk moduli") | `sort="-k_vrh"` on `/materials/summary/`, and also filter `"k_vrh_min": 0` so documents without the value drop out. Only summary, electrodes, XAS and molecules support `sort`; elsewhere fetch and sort yourself |
| What a compound decomposes into | `fields=["material_id","energy_above_hull","decomposes_to"]` |
| Direct or indirect gap, band edges | `fields=["band_gap","is_gap_direct","vbm","cbm"]` |
| Elastic, dielectric, magnetic, electrode, surface, provenance, XAS, synthesis data | the endpoint of that name (`/materials/elasticity/`, `/materials/dielectric/`, `/materials/magnetism/`, `/materials/insertion_electrodes/`, `/materials/surface_properties/`, `/materials/provenance/`, `/materials/xas/`, `/materials/synthesis/`); `describe_endpoint` lists its fields. Summary also carries `k_vrh`, `g_vrh`, `ordering`, `total_magnetization`, `e_total`, `n` |
| A structure as a file | `get_object("get_structure_by_material_id", {"material_id": "mp-149", "conventional_unit_cell": True}, format="cif")` or `"poscar"`; `format="summary"` gives formula, space group and lattice parameters |
| Which MP entry matches a given structure | `query("/materials/core/find_structure/", body=<pymatgen Structure as_dict>)` |
| Band structure or DOS, with a plot | `get_object("get_bandstructure_by_material_id", {"material_id": "mp-149"})` / `get_dos_by_material_id`; the summary gives gap, direct or indirect, and the transition k-points |
| Phonons, dynamical stability | `get_object("get_phonon_bandstructure_by_material_id", {...})` reports imaginary modes and the frequency range; `get_phonon_dos_by_material_id` gives Cv, S and F at several temperatures |
| A phase diagram | `get_object("materials.thermo.get_phase_diagram_from_chemsys", {"chemsys": "Fe-Li-O"})`: stable phases with formation energies, and the plot |
| Entries for your own thermodynamics | `get_object("get_entries_in_chemsys", {"elements": "Li-Fe-O"}, format="json")` |
| Pourbaix (aqueous stability) | `get_object("get_pourbaix_entries", {"chemsys": "Zn"})`, then build the diagram from the JSON |
| Equilibrium crystal shape, surface energies | `get_object("get_wulff_shape", {"material_id": "mp-149"})` |
| More rows than one call returns | pass `"_skip": N` in `params` and call again |

## Answering

- Give the value with its unit and the mp-id it came from; for lists, mp-id, formula and the property per row. What a field means, its unit and how MP computed it are in `describe_endpoint` (MP's own field descriptions) and `docs_search`; take them from there rather than from memory.
- `/materials/thermo/` returns one document per functional (`thermo_type`); filter `thermo_types` or use `/materials/summary/`, which carries one value per material.
- When a count is the question, report the total from the first line of the result, not the number of rows returned.
- Nested ids inside fields such as `decomposes_to`, and the ids returned by `find_structure`, may arrive in MP's AlphaID form (`mp-aaaaaaft`). They are valid MP ids; pass them back to `query` unchanged, and `material_ids` queries accept either form.
- A tool error that names a missing filter or field means the name was wrong: run `describe_endpoint` and use the name it lists.
