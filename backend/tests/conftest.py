"""Shared fixtures. Random-weight checkpoints are generated once and cached in tests/_fixtures
(ignored by Git). They are flagged ``fixture`` and carry no predictive meaning."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "scripts"))
os.environ["ONCOPIXEL_DISABLE_KEYRING"] = "1"
for var in ("ONCOPIXEL_CLASSIFIER_CKPT", "ONCOPIXEL_SEGMENTER_CKPT", "ONCOPIXEL_DATA_DIR"):
    os.environ.pop(var, None)

FIX = HERE / "_fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    if not (FIX / "classification" / "best.pt").exists() or not (FIX / "segmentation" / "tumor_seg_model.pt").exists():
        import make_test_fixtures as m

        (FIX / "classification").mkdir(parents=True, exist_ok=True)
        (FIX / "segmentation").mkdir(parents=True, exist_ok=True)
        m.make_classifier(FIX / "classification" / "best.pt")
        m.make_segmenter(FIX / "segmentation" / "tumor_seg_model.pt")
        import cv2

        cv2.imwrite(str(FIX / "phantom.png"), m.phantom())
    return FIX


@pytest.fixture()
def models_env(fixtures, monkeypatch):
    monkeypatch.setenv("ONCOPIXEL_CLASSIFIER_CKPT", str(fixtures / "classification" / "best.pt"))
    monkeypatch.setenv("ONCOPIXEL_SEGMENTER_CKPT", str(fixtures / "segmentation" / "tumor_seg_model.pt"))


@pytest.fixture()
def no_models_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ONCOPIXEL_CLASSIFIER_CKPT", str(tmp_path / "missing" / "best.pt"))
    monkeypatch.setenv("ONCOPIXEL_SEGMENTER_CKPT", str(tmp_path / "missing" / "seg.pt"))


def make_client(tmp_path, token="tok"):
    from fastapi.testclient import TestClient

    from oncopixel.main import create_app

    app = create_app(tmp_path / "data", app_token=token, start_watcher=False)
    return TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-OncoPixel-App": token})


@pytest.fixture()
def client(tmp_path, models_env):
    with make_client(tmp_path) as c:
        assert c.post("/api/auth/setup", json={"username": "gigi", "password": "Passw0rd!x"}).status_code == 200
        yield c


@pytest.fixture()
def client_no_models(tmp_path, no_models_env):
    with make_client(tmp_path) as c:
        assert c.post("/api/auth/setup", json={"username": "gigi", "password": "Passw0rd!x"}).status_code == 200
        yield c
