import gzip
import io
import json
import zipfile

import cv2
import numpy as np
import pydicom


def _setup(client, fixtures):
    p = client.post("/api/patients", json={"code": "P-001", "name": "Amina Benali", "age": 41, "sex": "F",
                                           "referring_physician": "Dr Khelifi", "history": "Headache"}).json()
    r = client.post("/api/import/upload", files=[("files", ("phantom.png", open(fixtures / "phantom.png", "rb"), "image/png"))],
                    data={"options": json.dumps({"patient_id": p["id"]})}).json()
    return p, client.get(f"/api/studies/{r['created'][0]}").json()


def test_full_flow(client, fixtures):
    p, st = _setup(client, fixtures)
    assert st["status"] == "pending" and st["patient"]["name"] == "Amina Benali"
    res = client.post(f"/api/studies/{st['id']}/analyze", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["skipped"] == {}
    c = body["classification"]
    assert c["label"] in {"glioma", "meningioma", "no_tumor", "pituitary"} and c["score_kind"] == "model_confidence_estimate"
    assert c["model"]["test_fixture"] is True and c["has_gradcam"] is True
    assert body["segmentation"]["edited"] is False and body["measurements"]["units"] == "px"
    sid = st["primary_slice_id"]
    for kind in ("original", "mask", "overlay", "gradcam", "gradcam_overlay", "probability"):
        r = client.get(f"/api/slices/{sid}/image/{kind}")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG", kind
    assert client.get(f"/api/slices/{sid}/image/uncertainty").status_code == 404
    assert client.post(f"/api/slices/{sid}/uncertainty").json()["segmentation"]["has_uncertainty"]
    assert client.get(f"/api/slices/{sid}/image/uncertainty_overlay").status_code == 200
    assert client.get(f"/api/studies/{st['id']}").json()["status"] == "analyzed"


def test_mask_edit_updates_measurements_and_resets(client, fixtures):
    _, st = _setup(client, fixtures)
    sid = st["primary_slice_id"]
    client.post(f"/api/studies/{st['id']}/analyze", json={})
    new = np.zeros((256, 256), np.uint8)
    cv2.circle(new, (128, 128), 20, 255, -1)
    png = cv2.imencode(".png", new)[1].tobytes()
    out = client.put(f"/api/slices/{sid}/mask", content=png).json()
    assert out["segmentation"]["edited"] is True and out["measurements"]["mask_edited"] is True
    assert abs(out["measurements"]["area_px"] - np.pi * 20 ** 2) < 60
    assert client.post(f"/api/slices/{sid}/resegment", json={"threshold": 0.6}).status_code == 409
    assert client.post(f"/api/slices/{sid}/resegment", json={"threshold": 0.6, "discard_edits": True}).status_code == 200
    client.put(f"/api/slices/{sid}/mask", content=png)
    assert client.post(f"/api/slices/{sid}/mask/reset").json()["segmentation"]["edited"] is False
    wrong = cv2.imencode(".png", np.zeros((10, 10), np.uint8))[1].tobytes()
    assert client.put(f"/api/slices/{sid}/mask", content=wrong).status_code == 409


def test_spacing_gives_millimetres(client, fixtures):
    _, st = _setup(client, fixtures)
    client.post(f"/api/studies/{st['id']}/analyze", json={})
    out = client.put(f"/api/studies/{st['id']}/spacing", json={"row_mm": 0.5, "col_mm": 0.5}).json()
    m = client.get(f"/api/slices/{out['primary_slice_id']}").json()["measurements"]
    assert m["units"] == "mm" and abs(m["area_mm2"] - m["area_px"] * 0.25) < 1e-6


def test_review_workflow_and_search(client, fixtures):
    _, st = _setup(client, fixtures)
    assert client.post(f"/api/studies/{st['id']}/review", json={"decision": "reviewed"}).status_code == 422
    client.post(f"/api/studies/{st['id']}/analyze", json={})
    r = client.post(f"/api/studies/{st['id']}/review", json={"decision": "reviewed", "note": "agree"}).json()
    assert r["status"] == "reviewed" and r["reviewed_by"] == "gigi" and r["review_note"] == "agree"
    assert client.get("/api/studies", params={"status": "reviewed"}).json()["total"] == 1
    assert client.get("/api/studies", params={"q": "benali"}).json()["total"] == 1
    assert client.get("/api/studies", params={"q": "nobody"}).json()["total"] == 0
    d = client.get("/api/dashboard").json()
    assert d["total_studies"] == 1 and d["analyses_completed"] == 1 and d["pending_reviews"] == 0
    assert client.get("/api/activity").json()["total"] > 3


def test_exports(client, fixtures):
    _, st = _setup(client, fixtures)
    sid = st["id"]
    client.post(f"/api/studies/{sid}/analyze", json={})
    pdf = client.get(f"/api/studies/{sid}/export/pdf", params={"lang": "fr"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    docx = client.get(f"/api/studies/{sid}/export/docx")
    assert zipfile.ZipFile(io.BytesIO(docx.content)).testzip() is None
    js = client.get(f"/api/studies/{sid}/export/json").json()
    assert js["patient"]["name"] == "Amina Benali" and js["test_fixture"] is True
    for fmt in ("json", "csv"):
        anon = client.get(f"/api/studies/{sid}/export/{fmt}", params={"anonymize": True})
        assert b"Amina" not in anon.content and b"Benali" not in anon.content
    assert len(gzip.decompress(client.get(f"/api/studies/{sid}/export/mask-nifti").content)) > 348
    for fmt, member in (("dicom-seg", "seg.dcm"), ("dicom-sr", "report_sr.dcm")):
        z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/studies/{sid}/export/{fmt}", params={"anonymize": True}).content))
        assert str(pydicom.dcmread(io.BytesIO(z.read(member))).PatientName) == "ANONYMOUS^"
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/studies/{sid}/export/dicom-sr").content))
    sr = pydicom.dcmread(io.BytesIO(z.read("report_sr.dcm")))
    assert "Benali" in str(sr.PatientName) and len(sr.ContentSequence) > 0
    assert client.get(f"/api/studies/{sid}/export/exe").status_code == 404
    assert client.get(f"/api/studies/{sid}/export/pdf", params={"save": True}).json()["name"].endswith(".pdf")


def test_comparison_requires_same_patient(client, fixtures):
    p, a = _setup(client, fixtures)
    other = client.post("/api/import/upload", files=[("files", ("p.png", open(fixtures / "phantom.png", "rb"), "image/png"))]).json()["created"][0]
    for s in (a["id"], other):
        client.post(f"/api/studies/{s}/analyze", json={})
    assert client.get("/api/compare", params={"a": a["id"], "b": other}).status_code == 422
    client.patch(f"/api/studies/{other}", json={"patient_id": p["id"]})
    r = client.get("/api/compare", params={"a": a["id"], "b": other}).json()
    assert r["mask_overlap"]["dice"] == 1.0 and "images_not_registered" in r["notes"]
    assert client.get("/api/compare/overlay.png", params={"a": a["id"], "b": other}).status_code == 200


def test_import_rejects_unsupported_images(client, tmp_path):
    cv2.imwrite(str(tmp_path / "flat.png"), np.full((200, 200), 128, np.uint8))
    cv2.imwrite(str(tmp_path / "tiny.png"), np.random.randint(0, 255, (20, 20), np.uint8))
    (tmp_path / "notes.txt").write_text("hello")
    r = client.post("/api/import/paths", json={"paths": [str(tmp_path)]}).json()
    codes = {w["code"] for rej in r["rejected"] for w in rej["warnings"]}
    assert r["created"] == [] and {"image_blank_or_flat", "image_too_small"} <= codes


def test_colour_image_is_accepted_with_warning(client, tmp_path):
    cv2.imwrite(str(tmp_path / "c.png"), np.random.randint(0, 255, (200, 200, 3), np.uint8))
    r = client.post("/api/import/paths", json={"paths": [str(tmp_path / "c.png")]}).json()
    st = client.get(f"/api/studies/{r['created'][0]}").json()
    assert any(w["code"] == "image_is_colour" for w in st["slices"][0]["warnings"]) and st["flagged"]


def test_only_png_and_jpg_are_imported(client, tmp_path):
    (tmp_path / "scan.dcm").write_bytes(b"\0" * 128 + b"DICM")
    cv2.imwrite(str(tmp_path / "a.bmp"), np.random.randint(0, 255, (200, 200), np.uint8))
    r = client.post("/api/import/paths", json={"paths": [str(tmp_path)]}).json()
    assert r["created"] == [] and r["rejected"][0]["warnings"][0]["code"] == "no_supported_files"


def test_clinician_decision(client, fixtures):
    _, st = _setup(client, fixtures)
    u = f"/api/studies/{st['id']}/clinician-decision"
    assert client.post(u, json={"decision": "agree"}).json()["clinician_decision"] == "agree"
    d = client.post(u, json={"decision": "change", "label": "pituitary"}).json()
    assert d["clinician_decision"] == "change" and d["clinician_class"] == "pituitary"
    assert client.post(u, json={"decision": "change", "label": "bogus"}).status_code == 422
    assert client.post(u, json={"decision": "reject"}).json()["clinician_class"] is None
    assert client.get(f"/api/studies/{st['id']}").json()["clinician_decision"] == "reject"
    sid = st["id"]
    client.post(f"/api/studies/{sid}/analyze", json={})  # re-analysis clears the old verdict
    assert client.get(f"/api/studies/{sid}").json()["clinician_decision"] is None
    client.post(u, json={"decision": "change", "label": "pituitary"})
    js = client.get(f"/api/studies/{sid}/export/json").json()
    assert js["study"]["clinician_decision"] == "change" and js["study"]["clinician_class"] == "pituitary"
    assert "clinician_review,class,pituitary" in client.get(f"/api/studies/{sid}/export/csv").content.decode("utf-8-sig").replace('"', "")
    for fmt in ("pdf", "docx"):
        assert client.get(f"/api/studies/{sid}/export/{fmt}", params={"lang": "fr"}).status_code == 200


def test_backup_and_restore(client, fixtures):
    _, st = _setup(client, fixtures)
    b = client.post("/api/backup", json={"passphrase": "secret-pass1"}).json()
    data = client.get("/api/backup/download", params={"name": b["name"]}).content
    client.delete(f"/api/studies/{st['id']}")
    assert client.get("/api/studies").json()["total"] == 0
    bad = client.post("/api/backup/restore", data={"passphrase": "wrong-pass"}, files={"file": ("b.opbackup", data)})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "wrong_passphrase"
    ok = client.post("/api/backup/restore", data={"passphrase": "secret-pass1"}, files={"file": ("b.opbackup", data)})
    assert ok.status_code == 200
    client.post("/api/auth/login", json={"username": "gigi", "password": "Passw0rd!x"})
    assert client.get("/api/studies").json()["total"] == 1
    assert client.get(f"/api/slices/{st['primary_slice_id']}/image/original").status_code == 200
