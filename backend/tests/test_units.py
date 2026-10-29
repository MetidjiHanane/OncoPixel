import cv2
import numpy as np

from oncopixel.services import measurements as M
from oncopixel.services import validation as V


def _disk(r=30, size=200):
    g = np.full((size, size), 40, np.uint8)
    m = np.zeros((size, size), np.uint8)
    cv2.circle(m, (110, 90), r, 1, -1)
    g[m > 0] = 200
    return g, m


def test_measurements_of_a_disk():
    g, m = _disk(30)
    out = M.compute_measurements(g, m)
    assert abs(out["area_px"] - np.pi * 900) < 40
    assert 58 < out["max_diameter_px"] < 62 and 58 < out["min_diameter_px"] < 62
    assert out["circularity"] > 0.85 and out["n_components"] == 1
    assert abs(out["centroid_xy_px"][0] - 110) < 1 and abs(out["centroid_xy_px"][1] - 90) < 1
    assert out["intensity"]["mean"] == 200 and out["intensity"]["contrast_ratio"] > 4
    assert "area_mm2" not in out and out["units"] == "px"


def test_measurements_in_mm_and_empty_mask():
    g, m = _disk(30)
    out = M.compute_measurements(g, m, spacing=(0.5, 0.5))
    assert abs(out["area_mm2"] - out["area_px"] * 0.25) < 1e-9 and 29 < out["max_diameter_mm"] < 31
    empty = M.compute_measurements(g, np.zeros_like(m))
    assert empty["tumor_detected"] is False and "bbox_xyxy_px" not in empty


def test_midline_not_reported_for_sagittal():
    g, m = _disk(20)
    assert M.compute_measurements(g, m, plane="sagittal")["midline_distance_px"] is None


def test_compare_measurements():
    g, a = _disk(20)
    _, b = _disk(30)
    cmp = M.compare_measurements(M.compute_measurements(g, a), M.compute_measurements(g, b))
    area = next(r for r in cmp["rows"] if r["metric"] == "area")
    assert cmp["unit_system"] == "px" and area["percent"] > 100


def test_validation_rules():
    rng = np.random.default_rng(0)
    assert any(w["code"] == "image_blank_or_flat" for w in V.validate_pixels(np.full((100, 100), 7, np.uint8), None, 10**7))
    assert any(w["code"] == "image_too_small" for w in V.validate_pixels(rng.integers(0, 255, (30, 30)).astype(np.uint8), None, 10**7))
    ok = np.zeros((128, 128), np.uint8)
    ok[30:90, 30:90] = rng.integers(60, 255, (60, 60))
    codes = {w["code"] for w in V.validate_pixels(ok, 40.0, 10**7)}
    assert "image_is_colour" in codes and "not_verified_brain_t1" in codes
    assert V.sequence_warning("AX T2 FLAIR")["code"] == "sequence_not_t1" and V.sequence_warning("T1 MPRAGE") is None
