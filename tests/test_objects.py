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


def test_discovery_needs_no_network(monkeypatch):
    import mp_api.client.mprester as m

    def boom(url, **kw):
        raise AssertionError(f"network call to {url}")

    monkeypatch.setattr(m, "get", boom)  # requests.get as used by MPRester.get_emmet_version
    assert "get_structure_by_material_id" in objects.discover()


def test_band_structure_without_structure_still_summarizes():
    from pymatgen.core import Lattice
    from pymatgen.electronic_structure.bandstructure import BandStructureSymmLine
    from pymatgen.electronic_structure.core import Spin

    lat = Lattice.cubic(5.0).reciprocal_lattice
    bs = BandStructureSymmLine([[0, 0, 0], [0.5, 0, 0]], {Spin.up: np.array([[-1.0, -1.2], [1.0, 1.5]])}, lat, 0.0,
                               {"G": [0, 0, 0], "X": [0.5, 0, 0]})
    text, _ = objects.summarize(bs)
    assert text.startswith("Band structure") and "band gap: 2.000 eV" in text


def test_store_evicts_oldest_when_full(monkeypatch):
    monkeypatch.setattr(objects, "STORE_BYTES", 25)
    st = objects.Store()
    t1 = st.put(b"a" * 10, "1.json")
    t2 = st.put(b"b" * 10, "2.json")
    t3 = st.put(b"c" * 10, "3.json")
    assert st.get(t1) is None and st.get(t2) and st.get(t3)


def test_output_dir_is_never_the_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("MP_MCP_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert objects.output_dir() == (tmp_path / "mp-mcp" / "objects").resolve()
    monkeypatch.setenv("MP_MCP_OUTPUT_DIR", str(tmp_path / "x"))
    assert objects.output_dir() == (tmp_path / "x").resolve()
