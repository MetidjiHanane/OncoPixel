"""Without checkpoints the application must say so and must not produce analysis results."""


def _import(client, fixtures):
    r = client.post("/api/import/upload", files=[("files", ("phantom.png", open(fixtures / "phantom.png", "rb"), "image/png"))])
    assert r.status_code == 200
    return r.json()


def test_models_status_missing(client_no_models):
    st = client_no_models.get("/api/models").json()
    assert st["all_ready"] is False
    assert all(m["state"] == "missing" and m["code"] == "file_not_found" for m in st["models"].values())


def test_analyze_returns_409_and_stores_nothing(client_no_models, fixtures):
    sid = _import(client_no_models, fixtures)["created"][0]
    r = client_no_models.post(f"/api/studies/{sid}/analyze", json={})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "MODEL_MISSING" and err["state"] == "missing"
    st = client_no_models.get(f"/api/studies/{sid}").json()
    assert st["status"] == "pending" and st["prediction"] is None and st["segmented"] is False


def test_import_still_works_without_models(client_no_models, fixtures):
    assert _import(client_no_models, fixtures)["rejected"] == []
