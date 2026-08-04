"""Test authentication: token hashing, verification, edge cases."""

import json

import pytest

from remote_claws.auth import HashedTokenVerifier, hash_token, load_token_hash


def test_hash_is_sha256_hex():
    h = hash_token("test_token")
    assert len(h) == 64  # SHA-256 = 32 bytes = 64 hex chars
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic():
    assert hash_token("abc") == hash_token("abc")


def test_different_tokens_different_hashes():
    assert hash_token("aaa") != hash_token("bbb")


@pytest.mark.asyncio
async def test_verify_correct_token():
    verifier = HashedTokenVerifier(hash_token("valid_token"))
    result = await verifier.verify_token("valid_token")
    assert result is not None
    assert result.scopes == ["*"]


@pytest.mark.asyncio
async def test_verify_wrong_token():
    verifier = HashedTokenVerifier(hash_token("valid_token"))
    result = await verifier.verify_token("wrong_token")
    assert result is None


@pytest.mark.asyncio
async def test_verify_empty_token():
    verifier = HashedTokenVerifier(hash_token("valid_token"))
    result = await verifier.verify_token("")
    assert result is None


@pytest.mark.asyncio
async def test_verify_timing_safe():
    """Timing-safe comparison should reject even nearly-correct tokens."""
    verifier = HashedTokenVerifier(hash_token("aaaa...zz"))
    almost_right = "aaaa...zy"
    result = await verifier.verify_token(almost_right)
    assert result is None


def test_load_token_hash_from_file(tmp_path):
    auth_file = tmp_path / ".remote-claws-auth.json"
    expected_hash = hash_token("test_token_123")
    auth_file.write_text(json.dumps({"token_hash": expected_hash}))
    loaded = load_token_hash(str(auth_file))
    assert loaded == expected_hash


def test_load_token_hash_missing_file():
    try:
        load_token_hash("/nonexistent/file.json")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


def test_load_token_hash_invalid_json(tmp_path):
    auth_file = tmp_path / "bad.json"
    auth_file.write_text("{not valid json")
    try:
        load_token_hash(str(auth_file))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_load_token_hash_missing_key(tmp_path):
    auth_file = tmp_path / "nohash.json"
    auth_file.write_text(json.dumps({"some_other_key": "value"}))
    try:
        load_token_hash(str(auth_file))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
