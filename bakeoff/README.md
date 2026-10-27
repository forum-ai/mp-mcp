# MP MCP bake-off: five questions, three setups

The question this answers: what does the hosted MP MCP give that bare Claude, or Claude Code writing `mp_api` code, does not? The five questions run from a simple fact that every setup should get right to a screening query the MCP's tools cannot express. Scoring copies the fly-brain MCP study: 2 for precisely correct, 1 for generally correct, 0 for wrong, with a separate flag for any invented detail.

## Setups

Use the same Claude model in every setup, and write it down. Start a fresh conversation for every question.

- **A · Bare Claude.** A new chat in claude.ai or Claude Desktop with web search off, no connectors, and no code execution.
- **B · Claude + the old MP MCP.** Claude Desktop with only the old server connected (mp-api's `search`/`fetch` server) and code execution off.
- **C · Claude + this server.** The same, with only this server connected.
- **D · Claude Code + mp-api (optional).** Claude Code in an empty folder with `MP_API_KEY` exported, no MCP servers, and permission to `pip install mp-api`: the ceiling, since it can write any query.

The answer key comes from running `./make_answer_key.sh` with your key exported. It builds a `.venv` inside this folder on the first run and writes `answer_key.md`. Run it the same day as the setups, because MP data changes between database releases.

## The five prompts

Paste each one exactly as written.

**Q1 · Simple fact (control).** According to the Materials Project, what are the band gap and the energy above hull of silicon in the diamond structure (mp-149), and what is its conventional cubic lattice parameter?

**Q2 · Long tail with polymorphs.** List every NaFePO4 entry in the Materials Project with its mp-id, space group and energy above hull in eV/atom. Which one does the Materials Project predict is the ground state?

**Q3 · Multi-hop thermodynamics.** In the Materials Project, what is the energy above hull of the lowest-energy Li7P3S11 entry, and what phases does the Materials Project say it decomposes into? Give mp-ids.

**Q4 · Screening.** Using the Materials Project, list the stable ternary oxides containing Ba (on the convex hull) whose band gap is between 2 and 3 eV. Give the total count and up to 10 examples with mp-id and band gap.

**Q5 · Structure handoff.** Give the Materials Project's conventional standard cell for layered LiCoO2 (R-3m): the mp-id, the lattice parameters a and c in Å, the number of atoms in the cell, and the structure as a CIF.

## What each question separates

- **Q1** is the control. Silicon is in every textbook, so a gap here would mean the setup itself is broken. The lattice parameter also tests whether the answer uses the 8-atom conventional cell rather than MP's 2-atom primitive cell.
- **Q2** needs a list of polymorphs plus a hull energy for each. A bare model has to recall mp-ids it has rarely seen. Through the old MCP it takes one `search` and then one `fetch` per entry; through this server it is one `query`.
- **Q3** needs the decomposition products. The old MCP's `fetch` returns the energy above hull but not what the compound decomposes into, so the model has to dig it out of a printed plot object. Here it is one `query` asking for the `decomposes_to` field.
- **Q4** filters by a property range. The old MCP's `search` takes only a formula, a chemical system or keywords, so this question cannot be asked through it. Here it is one `query` with `band_gap_min`, `band_gap_max`, `is_stable` and `elements`.
- **Q5** tests the structure itself. A bare model will tend to give the experimental lattice parameters (a ≈ 2.82 Å, c ≈ 14.05 Å), not MP's computed ones. An answer through an MCP may give the stored cell, which may be the 4-atom rhombohedral cell rather than the 12-atom hexagonal one. The key's note under Q5 says which cell is stored.

## Scoring

Score against `answer_key.md` with these tolerances: mp-ids exact, energies within 0.005 eV/atom, gaps within 0.05 eV, and lattice parameters within 0.01 Å. For lists, record how many of the key's items the answer got, and how many of its items are not in the key.

- **2 · precisely correct:** every id and number in the answer matches the key.
- **1 · generally correct:** the conclusion is right, but a number is off or an item is missing.
- **0 · wrong or refused.**
- **Invented detail (Y/N):** the answer states a fact that is neither in the key nor marked as uncertain. Score this separately from correctness, because in the fly-brain study it stayed at the same rate with or without the database.

| Q | A score | A invented | B score | B invented | B tool calls | C score | C invented | C tool calls | D score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |
| 4 | | | | | | | | | |
| 5 | | | | | | | | | |

Model used: ____ · MP database version (from the key): ____ · Date: ____
