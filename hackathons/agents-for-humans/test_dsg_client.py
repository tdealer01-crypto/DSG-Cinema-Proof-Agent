import pytest

from dsg_client import VerificationError, validate_receipt


def _receipt(**overrides):
    value = {
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "decision": "ALLOW",
        "proof_hash": "a" * 64,
        "request_hash": "b" * 64,
        "context_hash": "c" * 64,
    }
    value.update(overrides)
    return value


def test_valid_receipt_passes():
    receipt = _receipt()
    assert validate_receipt(receipt) is receipt


@pytest.mark.parametrize(
    "overrides",
    [
        {"verified": False},
        {"verification": "UNKNOWN"},
        {"decision": "PASS"},
        {"proof_hash": "short"},
        {"request_hash": "z" * 64},
        {"context_hash": None},
    ],
)
def test_invalid_receipt_fails_closed(overrides):
    with pytest.raises(VerificationError):
        validate_receipt(_receipt(**overrides))
