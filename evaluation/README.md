# Evaluation: does the server answer the questions people actually ask?

Two checks live here.

1. **`smoke_test.py`**: runs every tool against the live Materials Project API with your key, on about forty requests that cover the questions materials scientists bring to MP (a property by mp-id, polymorphs of a formula, a stability screen with ranges, a count, paging, sorting, a structure as CIF, band structures, phonons, phase diagrams, electrodes, synthesis recipes, docs). It prints one line per request and exits non-zero if anything fails. Run it after changing the server, after an `mp-api` upgrade, and after an MP database release.
2. **The twelve-question comparison** below, with `answer_key.py` computing the correct answers from the live API, for comparing this server with a bare model, with another MP connector, and with a model writing `mp-api` code.

Both need your MP API key (<https://next-gen.materialsproject.org/api>). Run them from a clone of this repository:

```
export MP_API_KEY=your_key_here
uv run evaluation/smoke_test.py          # about two minutes
uv run evaluation/answer_key.py          # writes evaluation/answer_key.md
```

`uv run` builds the project's environment on first use. The key is read from the environment and never written to disk; `answer_key.md` is git-ignored because it changes with every database release.

## The comparison

The question it answers: what does this server give that a bare model, a simpler MP connector (one offering only `search` and `fetch`, such as the server bundled with `mp-api`) or Claude Code writing `mp_api` code does not? The twelve questions run from a fact every setup should get right to screens and objects that need the full API. Scoring is 2 for precisely correct, 1 for generally correct, 0 for wrong, with a separate flag for any invented detail, because a connector can raise correctness and still leave fabrication untouched, and the two must be seen separately.

### Setups

Use the same model in every setup, and write it down. Start a fresh conversation for every question.

- **A · Bare model.** A new chat with web search off, no connectors, no code execution.
- **B · Model + a search/fetch connector.** Only `mp-api`'s bundled MCP server connected, code execution off.
- **C · Model + this server.** Only this server connected, code execution off.
- **D · Claude Code + mp-api (optional).** Claude Code in an empty folder with `MP_API_KEY` exported, no MCP servers, and permission to `pip install mp-api`: the ceiling, since it can write any query.

### The twelve prompts

Paste each one exactly as written.

**Q1 · Simple fact (control).** According to the Materials Project, what are the band gap and the energy above hull of silicon in the diamond structure (mp-149), and what is its conventional cubic lattice parameter?

**Q2 · Polymorphs.** List every NaFePO4 entry in the Materials Project with its mp-id, space group and energy above hull in eV/atom. Which one does the Materials Project predict is the ground state?

**Q3 · Decomposition.** In the Materials Project, what is the energy above hull of the lowest-energy Li7P3S11 entry, and what phases does the Materials Project say it decomposes into? Give mp-ids.

**Q4 · Property screen.** Using the Materials Project, list the stable ternary oxides containing Ba (on the convex hull) whose band gap is between 2 and 3 eV. Give the total count and up to 10 examples with mp-id and band gap.

**Q5 · Structure handoff.** Give the Materials Project's conventional standard cell for layered LiCoO2 (R-3m): the mp-id, the lattice parameters a and c in Å, the number of atoms in the cell, and the structure as a CIF.

**Q6 · Nature of the gap.** According to the Materials Project, is the band gap of zinc-blende GaAs (mp-2534) direct or indirect, what is its value, and where are the valence band maximum and conduction band minimum in energy?

**Q7 · Ranking.** Which ten stable binary oxides in the Materials Project have the highest Voigt-Reuss-Hill bulk modulus? Give mp-id, formula and bulk modulus in GPa.

**Q8 · Phonons.** Does the Materials Project's phonon band structure of silicon (mp-149) show any imaginary modes, and what is the highest phonon frequency in THz?

**Q9 · Dielectric.** What are the total, electronic and ionic dielectric constants and the refractive index of rutile TiO2 (mp-2657) in the Materials Project?

**Q10 · Magnetism.** What magnetic ordering and total magnetization per formula unit does the Materials Project give for the lowest-energy Fe3O4 entry, and what is its mp-id?

**Q11 · Electrodes.** For the Materials Project's LiFePO4/FePO4 insertion electrode, what are the average voltage, gravimetric capacity and the volume change on lithiation?

**Q12 · Phase diagram.** Which phases are stable in the Li-Fe-O chemical system according to the Materials Project, and what is the formation energy per atom of each?

### What each question separates

- **Q1** is the control. Silicon is in every textbook, so a gap here means the setup itself is broken. The lattice parameter tests whether the answer uses the 8-atom conventional cell rather than MP's 2-atom primitive cell.
- **Q2** needs a list plus a hull energy for each. A bare model must recall mp-ids it has rarely seen. Through a search/fetch connector it is one `search` and one `fetch` per entry; here it is one `query`.
- **Q3** needs decomposition products. A search/fetch connector returns the energy above hull but not what the compound decomposes into. Here it is one `query` asking for the `decomposes_to` field.
- **Q4** filters by a property range. A connector whose search takes only a formula, a chemical system or keywords cannot ask the question at all. Here it is one `query` with `band_gap_min`, `band_gap_max`, `is_stable` and `elements`.
- **Q5** tests the structure itself. A bare model tends to give experimental lattice parameters (a ≈ 2.82 Å, c ≈ 14.05 Å), not MP's computed ones. An MCP answer may give the stored 4-atom rhombohedral cell rather than the 12-atom hexagonal one; the key says which cell is stored. Here `get_object(..., args={'conventional_unit_cell': true}, format='cif')` gives the CIF directly.
- **Q6** needs four numbers from one document (`band_gap`, `is_gap_direct`, `vbm`, `cbm`) and the right sign convention.
- **Q7** needs server-side sorting (`sort='-k_vrh'` on `/materials/summary/`) or a large pull sorted by the model; a search/fetch connector cannot ask it.
- **Q8** needs a phonon object, not a document: `get_object('get_phonon_bandstructure_by_material_id')`.
- **Q9** and **Q10** test endpoints beyond summary (dielectric, magnetism) and whether the model finds them with `list_endpoints`.
- **Q11** tests the electrode endpoint, whose documents are keyed by battery id rather than mp-id.
- **Q12** needs the precomputed phase diagram object and a formation energy per stable phase.

### Scoring

Score against `answer_key.md` with these tolerances: mp-ids exact, energies within 0.005 eV/atom, gaps within 0.05 eV, lattice parameters within 0.01 Å, moduli within 2 GPa, dielectric constants within 2 percent, voltages within 0.02 V, capacities within 2 mAh/g. For lists, record how many of the key's items the answer got and how many of its items are not in the key.

- **2 · precisely correct:** every id and number matches the key.
- **1 · generally correct:** the conclusion is right, but a number is off or an item is missing.
- **0 · wrong or refused.**
- **Invented detail (Y/N):** the answer states a fact that is neither in the key nor marked as uncertain. Score it separately from correctness: a connector can make answers more often right without making them less often invented, and only separate columns show which happened.

| Q | A score | A invented | B score | B invented | B tool calls | C score | C invented | C tool calls | D score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |
| 4 | | | | | | | | | |
| 5 | | | | | | | | | |
| 6 | | | | | | | | | |
| 7 | | | | | | | | | |
| 8 | | | | | | | | | |
| 9 | | | | | | | | | |
| 10 | | | | | | | | | |
| 11 | | | | | | | | | |
| 12 | | | | | | | | | |

Model used: ____ · MP database version (from the key): ____ · Date: ____
