import pytest

from unstop_mcp.client import parse_opportunity_id
from unstop_mcp.crypto import build_fernet, decrypt_enc_data, encrypt_enc_data, maybe_decrypt
from unstop_mcp.errors import InvalidInput, UpstreamError
from unstop_mcp.models import detail, html_to_text, summarize

from .conftest import raw_opportunity


def test_enc_data_roundtrip():
    payload = {"access_token": "abc", "id": 7, "name": "Ä user"}
    assert decrypt_enc_data(encrypt_enc_data(payload)) == payload


def test_maybe_decrypt_top_level_and_nested():
    enc = encrypt_enc_data({"x": 1})
    assert maybe_decrypt({"encData": enc}) == {"x": 1}
    assert maybe_decrypt({"data": {"encData": enc}, "ok": True}) == {"data": {"x": 1}, "ok": True}
    assert maybe_decrypt({"plain": 1}) == {"plain": 1}


def test_decrypt_garbage_raises_upstream_error():
    with pytest.raises(UpstreamError):
        decrypt_enc_data("bm90IGpzb24=")


def test_fernet_key_generation_is_persistent(tmp_path):
    f1, generated = build_fernet(None, tmp_path / "k")
    f2, generated2 = build_fernet(None, tmp_path / "k")
    assert generated and not generated2
    assert f2.decrypt(f1.encrypt(b"hi")) == b"hi"


def test_html_to_text():
    text = html_to_text("<p>Hello&nbsp;<b>world</b></p><ul><li>a</li><li>b</li></ul><script>evil()</script>")
    assert "Hello world" in text and "- a" in text and "- b" in text and "evil" not in text
    assert html_to_text("x " * 1000, max_chars=50).endswith("[truncated]")


def test_summarize():
    s = summarize(raw_opportunity())
    assert s.title == "PromptWars"
    assert s.team_size == "1-4"
    assert s.total_cash_prize == 15000 and s.prize_currency == "INR"
    assert s.skills == ["AI", "Python"]
    assert s.registration_open is True and s.paid_entry is False


def test_detail():
    d = detail(raw_opportunity())
    assert d.rounds[0].title == "Round 1"
    assert d.eligibility == {"sector": ["students"]}
    assert "Build & ship" in d.description and "<" not in d.description
    assert d.prizes[0].details == "Pool up to 50k"




@pytest.mark.parametrize(
    "value,expected",
    [
        (1817824, 1817824),
        ("1817824", 1817824),
        ("https://unstop.com/hackathons/promptwars-x-nexora-1817824", 1817824),
        ("https://unstop.com/jobs/seo-executive-flymedia-1829237?lb=abc", 1829237),
    ],
)
def test_parse_opportunity_id(value, expected):
    assert parse_opportunity_id(value) == expected


def test_parse_opportunity_id_rejects_garbage():
    with pytest.raises(InvalidInput):
        parse_opportunity_id("hello")


@pytest.mark.parametrize("value,expected", [(1, 1), (0, 0), ("25", 25), ("2.0", 2), (True, None), (None, None),
                                            ("", None), ("abc", None), (float("inf"), None)])
def test_int_helper(value, expected):
    from unstop_mcp.models import _int

    assert _int(value) == expected
