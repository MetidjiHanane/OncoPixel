import pytest

from oncopixel import security as S
from conftest import make_client


def test_password_hash_roundtrip():
    h = S.hash_password("Passw0rd!x")
    assert S.verify_password("Passw0rd!x", h) and not S.verify_password("wrong", h)
    assert "Passw0rd" not in h


def test_password_policy():
    with pytest.raises(S.PasswordPolicyError):
        S.check_password_policy("short1")
    with pytest.raises(S.PasswordPolicyError):
        S.check_password_policy("onlyletters")
    S.check_password_policy("longenough1")


def test_lock_schedule():
    assert S.lock_seconds_for(4) == 0
    assert S.lock_seconds_for(5) == 30 and S.lock_seconds_for(6) == 60
    assert S.lock_seconds_for(99) == S.MAX_LOCK_SECONDS


def test_vault_roundtrip_and_key_stability(tmp_path):
    v = S.Vault(tmp_path)
    token = v.encrypt_text("Jane Doe")
    assert b"Jane" not in token
    assert S.Vault(tmp_path).decrypt_text(token) == "Jane Doe"
    assert v.key_bytes() == S.Vault(tmp_path).key_bytes()


def test_login_lockout(tmp_path, models_env):
    with make_client(tmp_path) as c:
        c.post("/api/auth/setup", json={"username": "gigi", "password": "Passw0rd!x"})
        c.post("/api/auth/logout")
        assert c.get("/api/patients").status_code == 401
        for _ in range(4):
            assert c.post("/api/auth/login", json={"username": "gigi", "password": "bad"}).status_code == 401
        r = c.post("/api/auth/login", json={"username": "gigi", "password": "bad"})
        assert r.status_code == 423 and r.json()["error"]["retry_after"] > 0
        assert c.post("/api/auth/login", json={"username": "gigi", "password": "Passw0rd!x"}).status_code == 423


def test_app_token_and_host_guard(tmp_path, models_env):
    with make_client(tmp_path) as c:
        assert c.get("/api/auth/state", headers={"X-OncoPixel-App": "wrong"}).status_code == 403
        assert c.get("/api/auth/state", headers={"Host": "evil.example"}).status_code == 403
        assert c.get("/api/auth/state").status_code == 200


def test_setup_only_once(client):
    assert client.post("/api/auth/setup", json={"username": "other", "password": "Passw0rd!x"}).status_code == 409


def test_recovery_key_resets_password(tmp_path, models_env):
    with make_client(tmp_path) as c:
        r = c.post("/api/auth/setup", json={"username": "gigi", "password": "Passw0rd!x"}).json()
        key = r["recovery_key"]
        assert len(key.replace("-", "")) == 24
        c.post("/api/auth/logout")
        bad = c.post("/api/auth/reset", json={"username": "gigi", "recovery_key": "AAAA-BBBB-CCCC", "new_password": "Newpass12"})
        assert bad.status_code == 401
        weak = c.post("/api/auth/reset", json={"username": "gigi", "recovery_key": key, "new_password": "short"})
        assert weak.status_code == 422
        ok = c.post("/api/auth/reset", json={"username": "gigi", "recovery_key": key.lower(), "new_password": "Newpass12"})
        assert ok.status_code == 200 and ok.json()["recovery_key"] != key
        c.post("/api/auth/logout")
        assert c.post("/api/auth/login", json={"username": "gigi", "password": "Passw0rd!x"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "gigi", "password": "Newpass12"}).status_code == 200
        # the old key no longer works
        c.post("/api/auth/logout")
        assert c.post("/api/auth/reset", json={"username": "gigi", "recovery_key": key, "new_password": "Another123"}).status_code == 401
