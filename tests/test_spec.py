from mp_mcp import spec


def test_every_endpoint_comes_from_the_spec():
    api, source = spec.load_spec("bundled")
    eps = spec.endpoints(api)
    assert source == "bundled snapshot"
    assert len(eps) == sum(len(ops) for ops in api["paths"].values())
    summary = eps["/materials/summary/"]
    params = {p["name"]: p for p in summary.params}
    assert "band_gap_min" in params and params["band_gap_min"]["description"]
    assert "band_gap" in summary.fields and summary.fields["band_gap"]["description"]


def test_post_endpoint_keeps_its_body():
    eps = spec.endpoints(spec.load_spec("bundled")[0])
    assert eps["/materials/core/find_structure/"].method == "POST"
    assert eps["/materials/core/find_structure/"].body is not None


def test_normalize():
    assert spec.normalize("materials/summary") == "/materials/summary/"
    assert spec.normalize("/materials/summary/") == "/materials/summary/"
