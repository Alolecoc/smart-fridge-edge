from smart_fridge.thermal_live import LIVE_PAGE


def test_live_page_has_heat_scale_and_frame_endpoint() -> None:
    assert "rgb(0,40,255)" in LIVE_PAGE
    assert "rgb(255,0,0)" in LIVE_PAGE
    assert "fetch('/api/frame'" in LIVE_PAGE
    assert "centroid_x" in LIVE_PAGE
    assert "let rotation = 270" in LIVE_PAGE
    assert 'id="rotate"' in LIVE_PAGE
