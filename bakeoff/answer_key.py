"""Compute the answer key for the five bake-off questions from the live Materials Project API.

Reads MP_API_KEY from the environment and writes answer_key.md next to this file.
Run it through make_answer_key.sh, the same day as the arms, so every arm sees the same database version.
"""

import os
import sys
from datetime import date
from pathlib import Path

from mp_api.client import MPRester

HERE = Path(__file__).resolve().parent
OUT = HERE / "answer_key.md"


def lines_for_docs(docs, cols):
    rows = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for d in docs:
        rows.append("| " + " | ".join(str(f(d)) for _, f in cols) + " |")
    return rows


def lowest(docs):
    return min(docs, key=lambda d: d.energy_above_hull)


def main():
    if not os.environ.get("MP_API_KEY"):
        sys.exit("MP_API_KEY is not set; export it in this shell first.")

    out = []
    with MPRester() as mpr:
        out += [
            "# Answer key",
            "",
            f"Computed {date.today().isoformat()} from Materials Project database version {mpr.get_database_version()}.",
            "Energies are eV/atom on MP's default mixed GGA/GGA+U/r2SCAN hull; gaps are the summary band gap in eV.",
            "",
        ]

        # Q1: Si, mp-149
        si = mpr.materials.summary.search(material_ids=["mp-149"], fields=["material_id", "band_gap", "energy_above_hull"])[0]
        si_conv = mpr.get_structure_by_material_id("mp-149", conventional_unit_cell=True)
        out += [
            "## Q1 · Si (mp-149)",
            "",
            f"- band gap: {si.band_gap:.3f} eV",
            f"- energy above hull: {si.energy_above_hull:.4f} eV/atom",
            f"- conventional cubic a: {si_conv.lattice.a:.4f} Å ({len(si_conv)} atoms in the conventional cell)",
            "",
        ]

        # Q2: every NaFePO4 entry
        fields = ["material_id", "formula_pretty", "symmetry", "energy_above_hull", "theoretical"]
        nafepo4 = sorted(mpr.materials.summary.search(formula="NaFePO4", fields=fields), key=lambda d: d.energy_above_hull)
        out += ["## Q2 · NaFePO4 entries", ""]
        out += lines_for_docs(nafepo4, [
            ("mp-id", lambda d: d.material_id),
            ("space group", lambda d: d.symmetry.symbol),
            ("E above hull", lambda d: f"{d.energy_above_hull:.4f}"),
            ("theoretical", lambda d: d.theoretical),
        ])
        out += ["", f"Ground state: {nafepo4[0].material_id} ({nafepo4[0].symmetry.symbol}).", ""]

        # Q3: Li7P3S11 hull energy and decomposition
        lps = lowest(mpr.materials.summary.search(
            formula="Li7P3S11", fields=["material_id", "symmetry", "energy_above_hull", "decomposes_to"]))
        out += [
            "## Q3 · Li7P3S11",
            "",
            f"- lowest-energy entry: {lps.material_id} ({lps.symmetry.symbol})",
            f"- energy above hull: {lps.energy_above_hull:.4f} eV/atom",
            "- decomposes to:",
        ]
        for p in lps.decomposes_to or []:
            out.append(f"  - {p.formula} ({p.material_id}), amount {p.amount:.3f}")
        if not lps.decomposes_to:
            out.append("  - (on the hull, or MP lists no decomposition)")
        out.append("")

        # Q4: stable Ba ternary oxides with 2-3 eV gaps
        hits = sorted(mpr.materials.summary.search(
            elements=["Ba", "O"], num_elements=3, is_stable=True, band_gap=(2, 3),
            fields=["material_id", "formula_pretty", "band_gap"]), key=lambda d: d.formula_pretty)
        out += [f"## Q4 · Stable Ba–X–O ternaries with 2–3 eV gaps: {len(hits)} entries", ""]
        out += lines_for_docs(hits, [
            ("mp-id", lambda d: d.material_id),
            ("formula", lambda d: d.formula_pretty),
            ("gap", lambda d: f"{d.band_gap:.3f}"),
        ])
        out.append("")

        # Q5: LiCoO2 R-3m conventional (hexagonal) cell
        lco = lowest(mpr.materials.summary.search(
            formula="LiCoO2", spacegroup_symbol="R-3m", fields=["material_id", "energy_above_hull"]))
        conv = mpr.get_structure_by_material_id(lco.material_id, conventional_unit_cell=True)
        prim = mpr.get_structure_by_material_id(lco.material_id)
        out += [
            "## Q5 · LiCoO2, R-3m",
            "",
            f"- mp-id: {lco.material_id} (energy above hull {lco.energy_above_hull:.4f} eV/atom)",
            f"- conventional hexagonal cell: a = {conv.lattice.a:.4f} Å, c = {conv.lattice.c:.4f} Å, {len(conv)} atoms",
            f"- the stored cell has {len(prim)} atoms"
            + ("; an answer with that many atoms gave the stored primitive cell, not the conventional one" if len(prim) != len(conv) else ", the same as the conventional cell"),
            "",
            "```",
            conv.to(fmt="cif").strip(),
            "```",
            "",
        ]

    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
