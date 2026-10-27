import numpy as np

from mp_mcp import objects


def test_discovers_object_methods_from_mp_api():
    found = objects.discover()
    for name in ("get_bandstructure_by_material_id", "get_dos_by_material_id", "get_phonon_dos_by_material_id",
                 "get_entries_in_chemsys", "materials.thermo.get_phase_diagram_from_chemsys"):
        assert name in found
    assert "phonon" in objects.describe(found, "phonon")


def test_phase_diagram_summary():
    from pymatgen.analysis.phase_diagram import PDEntry, PhaseDiagram
    from pymatgen.core import Composition

    pd = PhaseDiagram([PDEntry(Composition(c), e) for c, e in [("Na", 0), ("Cl2", 0), ("NaCl", -8.4), ("NaCl3", -6)]])
    text, png = objects.summarize(pd)
    assert "Cl-Na" in text and "NaCl" in text and "eV/atom" in text


def test_dos_summary():
    from pymatgen.electronic_structure.core import Spin
    from pymatgen.electronic_structure.dos import Dos

    e = np.linspace(-5, 5, 201)
    d = np.where(np.abs(e) > 1, 1.0, 0.0)
    text, _ = objects.summarize(Dos(0.0, e, {Spin.up: d}))
    assert "gap" in text


def test_unknown_objects_fall_back_to_json_text():
    text, png = objects.summarize({"a": 1})
    assert "dict" in text and png is None
