"""A webhook trigger names only an HMAC digest its verifier can compute.

``validation_rules.signature_algorithm`` used to be stored as given. The
verifier looks the name up on ``hashlib`` at delivery time, so a typo such as
``sha-256`` was accepted on save and then failed every delivery. The trigger
payloads now hold it to the digests the verifier declares, and both read the
one list in ``webhook_verification``.
"""

from uuid import uuid4

import pytest
from agentarea_triggers.schemas.dto import TriggerCreate, TriggerUpdate
from agentarea_triggers.webhook_verification import (
    DEFAULT_SIGNATURE_ALGORITHM,
    HMAC_SIGNATURE_ALGORITHMS,
    generic_signature_scheme,
    signature_algorithm_error,
)
from pydantic import ValidationError

UNUSABLE = ["sha-256", "SHA256", "md5", "new", "", None, 256]


def _create(rules: dict) -> TriggerCreate:
    return TriggerCreate(
        name="hook",
        agent_id=uuid4(),
        trigger_type="webhook",
        webhook_type="generic",
        validation_rules=rules,
    )


def test_the_default_digest_is_one_of_the_allowed() -> None:
    assert set(HMAC_SIGNATURE_ALGORITHMS) == {"sha1", "sha256", "sha384", "sha512"}
    assert DEFAULT_SIGNATURE_ALGORITHM in HMAC_SIGNATURE_ALGORITHMS
    assert generic_signature_scheme({}).algorithm == DEFAULT_SIGNATURE_ALGORITHM


@pytest.mark.parametrize("algorithm", UNUSABLE)
def test_a_trigger_naming_an_unusable_digest_is_refused(algorithm) -> None:
    rules = {"signature_algorithm": algorithm}
    with pytest.raises(ValidationError, match="signature_algorithm must be one of"):
        _create(rules)
    with pytest.raises(ValidationError, match="signature_algorithm must be one of"):
        TriggerUpdate(validation_rules=rules)


@pytest.mark.parametrize("algorithm", HMAC_SIGNATURE_ALGORITHMS)
def test_every_allowed_digest_is_accepted(algorithm) -> None:
    rules = {"signature_algorithm": algorithm}
    assert _create(rules).validation_rules == rules
    assert TriggerUpdate(validation_rules=rules).validation_rules == rules


def test_rules_without_a_digest_are_left_alone() -> None:
    assert signature_algorithm_error(None) is None
    assert signature_algorithm_error({"signature_header": "X-Sig"}) is None
    assert _create({}).validation_rules == {}
    assert TriggerUpdate(validation_rules=None).validation_rules is None
