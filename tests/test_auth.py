import time

import httpx
import pytest

from unstop_mcp.auth.api_keys import SCOPE_READ, SCOPE_WRITE, ApiKeyStore, ApiKeyVerifier
from unstop_mcp.auth.session import UnstopSession, jwt_expiry
from unstop_mcp.auth.store import SessionStore
from unstop_mcp.crypto import build_fernet, encrypt_enc_data
from unstop_mcp.errors import AuthFailed, AuthRequired

from .conftest import make_jwt

OTP_VERIFY = "/api/micro/oauth/v2/login/otp/verify"
TOKEN = "/api/micro/oauth/v2/token"


# ---------------------------------------------------------------- session store

def test_store_encrypts_at_rest(tmp_path):
    fernet, _ = build_fernet("k1", tmp_path / "unused")
    store = SessionStore(tmp_path / "s", fernet)
    store.put("alice", UnstopSession(access_token="SECRET-TOKEN", refresh_token="R"))
    blob = (tmp_path / "s" / "alice.session").read_bytes()
    assert b"SECRET-TOKEN" not in blob
    assert store.get("alice").access_token == "SECRET-TOKEN"
    assert store.list_tenants() == ["alice"]


def test_store_wrong_key_asks_for_relogin(tmp_path):
    f1, _ = build_fernet("k1", tmp_path / "x")
    f2, _ = build_fernet("k2", tmp_path / "x")
    SessionStore(tmp_path, f1).put("a", UnstopSession(access_token="t"))
    with pytest.raises(AuthRequired):
        SessionStore(tmp_path, f2).get("a")


def test_store_rejects_path_traversal(tmp_path):
    fernet, _ = build_fernet("k", tmp_path / "x")
    with pytest.raises(ValueError):
        SessionStore(tmp_path, fernet).get("../etc/passwd")


def test_jwt_expiry():
    assert abs(jwt_expiry(make_jwt(100)) - (time.time() + 100)) < 5
    assert jwt_expiry("not-a-jwt") is None


# ---------------------------------------------------------------- login flows

async def test_otp_login_plain_response(runtime, mock_api):
    token = make_jwt(3600)
    mock_api.post(OTP_VERIFY).mock(
        return_value=httpx.Response(200, json={"access_token": token, "refresh_token": "r1", "id": 42})
    )
    session = await runtime.auth.verify_otp("a@b.com", "123456")
    assert session.access_token == token and session.refresh_token == "r1" and session.user_id == 42
    assert session.email == "a@b.com" and session.expires_at


async def test_otp_login_encrypted_response(runtime, mock_api):
    token = make_jwt(3600)
    mock_api.post(OTP_VERIFY).mock(
        return_value=httpx.Response(200, json={"encData": encrypt_enc_data({"access_token": token, "id": 7})})
    )
    session = await runtime.auth.verify_otp("a@b.com", "123456")
    assert session.access_token == token and session.user_id == 7


async def test_otp_login_wrong_code(runtime, mock_api):
    mock_api.post(OTP_VERIFY).mock(
        return_value=httpx.Response(200, json={"data": {"status": False, "message": "Incorrect OTP. Please try again."}})
    )
    with pytest.raises(AuthFailed, match="Incorrect OTP"):
        await runtime.auth.verify_otp("a@b.com", "000000")


async def test_otp_login_mfa(runtime, mock_api):
    mock_api.post(OTP_VERIFY).mock(return_value=httpx.Response(200, json={"status": "mfa_required"}))
    with pytest.raises(AuthFailed, match="multi-factor"):
        await runtime.auth.verify_otp("a@b.com", "123456")


async def test_otp_format_validated_locally(runtime):
    from unstop_mcp.errors import InvalidInput

    with pytest.raises(InvalidInput):
        await runtime.auth.verify_otp("a@b.com", "abc")


async def test_send_otp_failure(runtime, mock_api):
    mock_api.post("/api/micro/oauth/v2/login/otp/send").mock(
        return_value=httpx.Response(200, json={"data": {"status": False, "message": "No account"}})
    )
    with pytest.raises(AuthFailed, match="No account"):
        await runtime.auth.send_otp("x@y.com")


# ---------------------------------------------------------------- token lifecycle

async def test_get_session_requires_login(runtime):
    with pytest.raises(AuthRequired, match="unstop-mcp login"):
        await runtime.auth.get_session("default")


async def test_fallback_token_for_default_tenant(runtime):
    runtime.auth.fallback_token = "pasted"
    assert (await runtime.auth.get_session("default")).access_token == "pasted"
    with pytest.raises(AuthRequired):
        await runtime.auth.get_session("bob")


async def test_proactive_refresh(runtime, mock_api):
    runtime.sessions.put("default", UnstopSession(access_token=make_jwt(10), refresh_token="r1",
                                                  expires_at=time.time() + 10))
    new = make_jwt(3600)
    route = mock_api.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": new, "refresh_token": "r2"}))
    session = await runtime.auth.get_session("default")
    assert session.access_token == new and session.refresh_token == "r2"
    assert runtime.sessions.get("default").access_token == new  # persisted
    assert route.calls[0].request.content and b'"refresh_token":"r1"' in route.calls[0].request.content.replace(b" ", b"")


async def test_refresh_rejected(runtime, mock_api):
    runtime.sessions.put("default", UnstopSession(access_token="a", refresh_token="r", expires_at=time.time()))
    route = mock_api.post(TOKEN).mock(return_value=httpx.Response(401, json={"message": "Unauthorized action."}))
    with pytest.raises(AuthRequired, match="Sign in again"):
        await runtime.auth.get_session("default")
    # the dead session is forgotten, so the next call doesn't hit the refresh endpoint again
    assert runtime.sessions.get("default") is None
    with pytest.raises(AuthRequired, match="Not logged in"):
        await runtime.auth.get_session("default")
    assert route.call_count == 1


async def test_401_triggers_single_refresh_and_retry(runtime, mock_api):
    runtime.sessions.put("default", UnstopSession(access_token="old", refresh_token="r", expires_at=time.time() + 9999))
    mock_api.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "fresh"}))

    def handler(request):
        if request.headers["Authorization"] == "Bearer fresh":
            return httpx.Response(200, json={"data": {"id": 1, "name": "Asha", "email": "a@b.com", "mobile": "9999"}})
        return httpx.Response(401, json={"message": "Unauthenticated."})

    mock_api.get("/api/user/profile").mock(side_effect=handler)
    profile = await runtime.client.profile("default")
    assert profile.id == 1 and profile.name == "Asha"
    assert "9999" not in profile.model_dump_json()


# ---------------------------------------------------------------- API keys

def test_api_key_lifecycle(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    key, rec = store.create("alice", scopes=[SCOPE_READ, SCOPE_WRITE], label="laptop")
    assert key.startswith("usk_") and len(key) > 40
    assert key not in (tmp_path / "keys.json").read_text()
    assert store.lookup(key).tenant == "alice"
    assert store.lookup(key + "x") is None
    assert store.revoke(rec.id)
    assert store.lookup(key) is None


def test_api_key_expiry_and_bad_scope(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    key, rec = store.create("a", ttl_days=1)
    rec_list = store.list()
    rec_list[0].expires_at = time.time() - 1
    store._save()
    assert store.lookup(key) is None
    with pytest.raises(ValueError):
        store.create("a", scopes=["admin"])


def test_api_key_store_picks_up_external_changes(tmp_path):
    path = tmp_path / "keys.json"
    server_view = ApiKeyStore(path)
    assert server_view.list() == []
    key, _ = ApiKeyStore(path).create("bob")  # e.g. the CLI in another process
    assert server_view.lookup(key).tenant == "bob"


async def test_verifier(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    key, _ = store.create("carol")
    token = await ApiKeyVerifier(store).verify_token(key)
    assert token.client_id == "carol" and token.scopes == [SCOPE_READ]
    assert await ApiKeyVerifier(store).verify_token("Bearer nonsense") is None
