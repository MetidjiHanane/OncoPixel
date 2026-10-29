import pytest
import torch

from oncopixel.ml.classifier import CheckpointError, Classifier
from oncopixel.ml.registry import ModelRegistry, ModelUnavailable
from oncopixel.ml.segmentation import SegmentationService
from oncopixel.services import selftest


def test_classifier_loads_and_predicts(fixtures):
    clf = Classifier(fixtures / "classification" / "best.pt", device="cpu")
    out = clf.predict(selftest.phantom(), tta=True)
    assert list(out.probabilities) == ["glioma", "meningioma", "no_tumor", "pituitary"]
    assert abs(sum(out.probabilities.values()) - 1) < 1e-5
    assert clf.info()["test_fixture"] is True
    cam = clf.gradcam(selftest.phantom())
    assert cam.shape == (256, 256) and 0 <= cam.min() and cam.max() <= 1


def test_classifier_rejects_wrong_class_order(fixtures, tmp_path):
    ck = torch.load(fixtures / "classification" / "best.pt", map_location="cpu", weights_only=True)
    ck["classes"] = list(reversed(ck["classes"]))
    torch.save(ck, tmp_path / "bad.pt")
    with pytest.raises(CheckpointError) as e:
        Classifier(tmp_path / "bad.pt")
    assert e.value.code == "class_order_mismatch"


def test_classifier_rejects_mismatched_weights(fixtures, tmp_path):
    ck = torch.load(fixtures / "classification" / "best.pt", map_location="cpu", weights_only=True)
    ck["state"].pop(next(iter(ck["state"])))
    torch.save(ck, tmp_path / "bad.pt")
    with pytest.raises(CheckpointError) as e:
        Classifier(tmp_path / "bad.pt")
    assert e.value.code == "weights_do_not_match_architecture"


def test_classifier_rejects_garbage_file(tmp_path):
    (tmp_path / "x.pt").write_bytes(b"not a checkpoint")
    with pytest.raises(CheckpointError) as e:
        Classifier(tmp_path / "x.pt")
    assert e.value.code == "unreadable_checkpoint"


def test_segmenter_loads_and_aligns(fixtures):
    seg = SegmentationService(fixtures / "segmentation" / "tumor_seg_model.pt", device="cpu")
    img = selftest.phantom(300)
    prob, _ = seg.predict_prob(img, tta=False)
    assert prob.shape == img.shape and 0 <= prob.min() and prob.max() <= 1
    unc = seg.uncertainty(img, 0.5)
    assert unc["entropy"].shape == img.shape and unc["stats"]["calibrated"] is False


def test_segmenter_rejects_mismatched_weights(fixtures, tmp_path):
    ck = torch.load(fixtures / "segmentation" / "tumor_seg_model.pt", map_location="cpu", weights_only=True)
    ck["config"]["arch"]["encoder"] = "resnet18"
    torch.save(ck, tmp_path / "bad.pt")
    with pytest.raises(CheckpointError) as e:
        SegmentationService(tmp_path / "bad.pt")
    assert e.value.code == "weights_do_not_match_architecture"


def test_registry_reports_missing_without_fabricating(tmp_path):
    reg = ModelRegistry(lambda: {"device": "cpu", "classification_checkpoint": str(tmp_path / "a.pt"),
                                 "segmentation_checkpoint": str(tmp_path / "b.pt")})
    st = reg.status_all()
    assert not st["all_ready"] and {m["state"] for m in st["models"].values()} == {"missing"}
    with pytest.raises(ModelUnavailable):
        reg.classifier()


def test_selftest_passes_on_fixtures(fixtures):
    reg = ModelRegistry(lambda: {"device": "cpu", "classification_checkpoint": str(fixtures / "classification" / "best.pt"),
                                 "segmentation_checkpoint": str(fixtures / "segmentation" / "tumor_seg_model.pt")})
    r = selftest.run(reg)
    assert r["all_ok"] and r["test_fixture"]
