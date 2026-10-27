"""Compute the answer key for the twelve evaluation questions from the live Materials Project API.

Reads MP_API_KEY from the environment and writes answer_key.md next to this file. Run it the
same day as the comparison, so every setup sees the same database version. Each question is
computed on its own: if one fails (an mp-api change, a missing record), the key says so under
that question and the others are still written.

    export MP_API_KEY=...
    uv run evaluation/answer_key.py
"""

import os
import sys
import traceback
from datetime import date
from pathlib import Path

from mp_api.client import MPRester

HERE = Path(__file__).resolve().parent
OUT = HERE / "answer_key.md"


def table(rows, cols):
    out = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for d in rows:
        out.append("| " + " | ".join(str(f(d)) for _, f in cols) + " |")
    return out


def lowest(docs):
    return min(docs, key=lambda d: d.energy_above_hull)


def q1(mpr):
    si = mpr.materials.summary.search(material_ids=["mp-149"], fields=["material_id", "band_gap", "energy_above_hull"])[0]
    conv = mpr.get_structure_by_material_id("mp-149", conventional_unit_cell=True)
    return ["## Q1 · Si (mp-149)", "",
            f"- band gap: {si.band_gap:.3f} eV",
            f"- energy above hull: {si.energy_above_hull:.4f} eV/atom",
            f"- conventional cubic a: {conv.lattice.a:.4f} Å ({len(conv)} atoms in the conventional cell)"]


def q2(mpr):
    docs = sorted(mpr.materials.summary.search(formula="NaFePO4", fields=["material_id", "symmetry", "energy_above_hull", "theoretical"]),
                  key=lambda d: d.energy_above_hull)
    return ["## Q2 · NaFePO4 entries", ""] + table(docs, [
        ("mp-id", lambda d: d.material_id), ("space group", lambda d: d.symmetry.symbol),
        ("E above hull (eV/atom)", lambda d: f"{d.energy_above_hull:.4f}"), ("theoretical", lambda d: d.theoretical),
    ]) + ["", f"Ground state: {docs[0].material_id} ({docs[0].symmetry.symbol})."]


def q3(mpr):
    d = lowest(mpr.materials.summary.search(formula="Li7P3S11", fields=["material_id", "symmetry", "energy_above_hull", "decomposes_to"]))
    out = ["## Q3 · Li7P3S11", "", f"- lowest-energy entry: {d.material_id} ({d.symmetry.symbol})",
           f"- energy above hull: {d.energy_above_hull:.4f} eV/atom", "- decomposes to:"]
    for p in d.decomposes_to or []:
        out.append(f"  - {p.formula} ({p.material_id}), amount {p.amount:.3f}")
    if not d.decomposes_to:
        out.append("  - (on the hull, or MP lists no decomposition)")
    return out


def q4(mpr):
    hits = sorted(mpr.materials.summary.search(elements=["Ba", "O"], num_elements=3, is_stable=True, band_gap=(2, 3),
                                               fields=["material_id", "formula_pretty", "band_gap"]), key=lambda d: d.formula_pretty)
    return [f"## Q4 · Stable Ba–X–O ternaries with 2–3 eV gaps: {len(hits)} entries", ""] + table(hits, [
        ("mp-id", lambda d: d.material_id), ("formula", lambda d: d.formula_pretty), ("gap (eV)", lambda d: f"{d.band_gap:.3f}")])


def q5(mpr):
    lco = lowest(mpr.materials.summary.search(formula="LiCoO2", spacegroup_symbol="R-3m", fields=["material_id", "energy_above_hull"]))
    conv = mpr.get_structure_by_material_id(lco.material_id, conventional_unit_cell=True)
    prim = mpr.get_structure_by_material_id(lco.material_id)
    return ["## Q5 · LiCoO2, R-3m", "",
            f"- mp-id: {lco.material_id} (energy above hull {lco.energy_above_hull:.4f} eV/atom)",
            f"- conventional hexagonal cell: a = {conv.lattice.a:.4f} Å, c = {conv.lattice.c:.4f} Å, {len(conv)} atoms",
            f"- the stored cell has {len(prim)} atoms"
            + ("; an answer with that many atoms gave the stored primitive cell, not the conventional one" if len(prim) != len(conv) else ""),
            "", "```", conv.to(fmt="cif").strip(), "```"]


def q6(mpr):
    d = mpr.materials.summary.search(material_ids=["mp-2534"], fields=["material_id", "formula_pretty", "band_gap", "is_gap_direct", "vbm", "cbm"])[0]
    return ["## Q6 · GaAs (mp-2534) gap", "",
            f"- band gap: {d.band_gap:.3f} eV, {'direct' if d.is_gap_direct else 'indirect'}",
            f"- VBM: {d.vbm:.3f} eV, CBM: {d.cbm:.3f} eV (absolute energies from the calculation; their difference is the gap)"]


def q7(mpr):
    docs = mpr.materials.summary.search(elements=["O"], num_elements=2, is_stable=True, k_vrh=(50, None),
                                        fields=["material_id", "formula_pretty", "k_vrh"])
    docs = sorted((d for d in docs if d.k_vrh is not None), key=lambda d: -d.k_vrh)[:10]
    return ["## Q7 · Stable binary oxides with the highest K_VRH (top 10)", ""] + table(docs, [
        ("mp-id", lambda d: d.material_id), ("formula", lambda d: d.formula_pretty), ("K_VRH (GPa)", lambda d: f"{d.k_vrh:.0f}")])


def q8(mpr):
    bs = mpr.get_phonon_bandstructure_by_material_id("mp-149")
    return ["## Q8 · Si (mp-149) phonons", "",
            f"- imaginary modes: {bs.has_imaginary_freq()}",
            f"- lowest frequency: {float(bs.bands.min()):.3f} THz; highest: {float(bs.bands.max()):.2f} THz"]


def q9(mpr):
    d = mpr.materials.dielectric.search(material_ids=["mp-2657"], fields=["material_id", "e_total", "e_ionic", "e_electronic", "n"])[0]
    return ["## Q9 · Rutile TiO2 (mp-2657) dielectric", "",
            f"- total dielectric constant: {d.e_total:.2f}", f"- electronic: {d.e_electronic:.2f}", f"- ionic: {d.e_ionic:.2f}",
            f"- refractive index: {d.n:.3f}"]


def q10(mpr):
    d = lowest(mpr.materials.summary.search(formula="Fe3O4", fields=["material_id", "energy_above_hull", "ordering",
                                                                      "total_magnetization", "total_magnetization_normalized_formula_units"]))
    return ["## Q10 · Fe3O4 ground state magnetism", "",
            f"- mp-id: {d.material_id} (energy above hull {d.energy_above_hull:.4f} eV/atom)",
            f"- ordering: {d.ordering}",
            f"- total magnetization: {d.total_magnetization:.3f} μB per cell; {d.total_magnetization_normalized_formula_units:.3f} μB per formula unit"]


def q11(mpr):
    docs = mpr.materials.insertion_electrodes.search(working_ion="Li", elements=["Fe", "P", "O"], num_elements=3,
                                                     fields=["battery_id", "formula_charge", "formula_discharge", "average_voltage",
                                                             "capacity_grav", "max_delta_volume", "energy_grav"])
    docs = [d for d in docs if d.formula_discharge == "LiFePO4" or d.formula_charge == "FePO4"] or docs
    return ["## Q11 · LiFePO4 / FePO4 electrode", ""] + table(docs, [
        ("battery id", lambda d: d.battery_id), ("charged", lambda d: d.formula_charge), ("discharged", lambda d: d.formula_discharge),
        ("avg voltage (V)", lambda d: f"{d.average_voltage:.3f}"), ("capacity (mAh/g)", lambda d: f"{d.capacity_grav:.1f}"),
        ("Δvolume (fraction)", lambda d: f"{d.max_delta_volume:.3f}")])


def q12(mpr):
    pd = mpr.materials.thermo.get_phase_diagram_from_chemsys("Fe-Li-O")
    stable = sorted(pd.stable_entries, key=lambda e: e.composition.reduced_formula)
    return [f"## Q12 · Li-Fe-O phase diagram: {len(stable)} stable phases", ""] + table(stable, [
        ("formula", lambda e: e.composition.reduced_formula), ("entry id", lambda e: getattr(e, "entry_id", "") or ""),
        ("formation energy (eV/atom)", lambda e: f"{pd.get_form_energy_per_atom(e):.3f}")])


def main():
    if not os.environ.get("MP_API_KEY"):
        sys.exit("MP_API_KEY is not set; export it in this shell first.")
    out = []
    with MPRester() as mpr:
        out += ["# Answer key", "", f"Computed {date.today().isoformat()} from Materials Project database version {mpr.db_version}.",
                "Energies are eV/atom on MP's default mixed GGA/GGA+U/r2SCAN hull; gaps are the summary band gap in eV.", ""]
        for i, fn in enumerate([q1, q2, q3, q4, q5, q6, q7, q8, q9, q10, q11, q12], 1):
            try:
                out += fn(mpr) + [""]
            except Exception as exc:
                out += [f"## Q{i}", "", f"Could not compute: {type(exc).__name__}: {exc}", ""]
                traceback.print_exc()
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
