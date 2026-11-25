"""✍️ signed URL — determinism, การหมดอายุ, การปลอมแปลง, การผูก viewer/variant"""
import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from core.config import settings
from core.media_signing import (
    make_signature,
    sign_url,
    verify_signature,
)


@pytest.fixture
def image_id():
    return str(uuid.uuid4())


def test_exp_is_rounded_up_to_bucket():
    # ttl=900, step=300: now=1000 → 1900 → ปัดลงเป็น 1800
    exp, _ = make_signature("abc", "full", 7, now=1000)
    assert exp == 1800
    # now=1199 → 2099 → 1800 (ยังอยู่ bucket เดิม)
    exp, _ = make_signature("abc", "full", 7, now=1199)
    assert exp == 1800
    # now=1200 → 2100 → 2100 (bucket ถัดไป)
    exp, _ = make_signature("abc", "full", 7, now=1200)
    assert exp == 2100


def test_signature_is_deterministic_within_bucket(image_id):
    assert make_signature(image_id, "full", 3, now=1000) == make_signature(
        image_id, "full", 3, now=1100
    )


def test_signature_bound_to_viewer_and_variant(image_id):
    _, full_a = make_signature(image_id, "full", 1, now=1000)
    _, full_b = make_signature(image_id, "full", 2, now=1000)
    _, thumb_a = make_signature(image_id, "thumb", 1, now=1000)
    assert len({full_a, full_b, thumb_a}) == 3


def test_sign_url_shape(image_id):
    url = sign_url(image_id, "thumb", 42, now=1000)
    parsed = urlparse(url)
    assert parsed.path == f"/api/images/{image_id}"
    q = parse_qs(parsed.query)
    assert q["variant"] == ["thumb"]
    assert q["viewer"] == ["42"]
    assert re.fullmatch(r"\d+", q["exp"][0])
    assert re.fullmatch(r"[A-Za-z0-9_-]+", q["sig"][0])


def test_verify_roundtrip(image_id):
    exp, sig = make_signature(image_id, "full", 9, now=1000)
    assert verify_signature(image_id, "full", "9", str(exp), sig, now=1100) == (9, "full")


@pytest.mark.parametrize(
    "mutate",
    [
        {"viewer": "10"},
        {"variant": "thumb"},
        {"exp_delta": 300},
        {"sig": "AAAAAAAAAAAAAAAAAAAAAA"},
        {"sig": "short"},
        {"variant": "original"},
        {"viewer": "0"},
        {"viewer": "9x"},
        {"exp": "soon"},
    ],
)
def test_verify_rejects_tampering(image_id, mutate):
    exp, sig = make_signature(image_id, "full", 9, now=1000)
    params = {
        "variant": "full",
        "viewer": "9",
        "exp": str(exp),
        "sig": sig,
    }
    if "variant" in mutate:
        params["variant"] = mutate["variant"]
    if "viewer" in mutate:
        params["viewer"] = mutate["viewer"]
    if "exp" in mutate:
        params["exp"] = mutate["exp"]
    if "exp_delta" in mutate:
        params["exp"] = str(exp + mutate["exp_delta"])
    if "sig" in mutate:
        params["sig"] = mutate["sig"]
    assert verify_signature(image_id, params["variant"], params["viewer"], params["exp"], params["sig"], now=1100) is None


def test_expired_url_rejected(image_id):
    exp, sig = make_signature(image_id, "full", 9, now=1000)
    assert verify_signature(image_id, "full", "9", str(exp), sig, now=exp + 1) is None


def test_exp_too_far_in_future_rejected(image_id):
    """ลายเซ็นที่ยิง exp ไกลเกินกว่าที่ระบบออกให้ได้ (แม้ sig จะถูกต้องตามสูตร) ต้องปฏิเสธ"""
    from core.media_signing import _sign

    now = int(__import__("time").time())
    max_ok = now + settings.MEDIA_URL_SIGNING_TTL_SECONDS + settings.MEDIA_URL_EXP_ROUND_SECONDS
    far = max_ok + 3600
    sig = _sign(image_id, "full", 1, far)
    assert verify_signature(image_id, "full", "1", str(far), sig, now=now) is None


def test_missing_params_rejected(image_id):
    assert verify_signature(image_id, None, None, None, None) is None
    assert verify_signature(image_id, "full", None, "1", "x") is None


# ============================================================
# 🖼️ scope ของรูปกลาง (media) — แยกโดเมนลายเซ็นจากรูปของเรื่อง
# ============================================================
def test_media_scope_url_shape(image_id):
    url = sign_url(image_id, "thumb", 42, now=1000, scope="media")
    parsed = urlparse(url)
    assert parsed.path == f"/api/media/file/{image_id}"
    q = parse_qs(parsed.query)
    assert q["viewer"] == ["42"] and q["variant"] == ["thumb"]


def test_scopes_are_not_interchangeable(image_id):
    exp, sig = make_signature(image_id, "full", 7, now=1000, scope="media")
    assert verify_signature(image_id, "full", "7", str(exp), sig, now=1100, scope="media") == (7, "full")
    # ลายเซ็นของ media ใช้กับ scope default (เรื่อง) ไม่ได้ และกลับกัน
    assert verify_signature(image_id, "full", "7", str(exp), sig, now=1100) is None
    exp2, sig2 = make_signature(image_id, "full", 7, now=1000)
    assert verify_signature(image_id, "full", "7", str(exp2), sig2, now=1100, scope="media") is None


def test_unknown_scope_raises_on_sign(image_id):
    with pytest.raises(ValueError):
        sign_url(image_id, "full", 1, scope="nope")


def test_unknown_scope_verifies_none(image_id):
    exp, sig = make_signature(image_id, "full", 1, now=1000)
    assert verify_signature(image_id, "full", "1", str(exp), sig, now=1100, scope="nope") is None
