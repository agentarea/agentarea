"""Ids leave an installation only as an HMAC keyed by the installation's own id."""

import hashlib
import hmac

from agentarea_common.analytics import pseudonymize


def test_the_same_id_in_the_same_installation_hashes_the_same():
    assert pseudonymize("install-a", "user-1") == pseudonymize("install-a", "user-1")


def test_it_is_hmac_sha256_keyed_by_the_install_id_cut_to_16_hex_chars():
    expected = hmac.new(b"install-a", b"user-1", hashlib.sha256).hexdigest()[:16]

    assert pseudonymize("install-a", "user-1") == expected
    assert len(expected) == 16


def test_the_same_id_in_another_installation_hashes_differently():
    assert pseudonymize("install-a", "user-1") != pseudonymize("install-b", "user-1")


def test_different_ids_hash_differently():
    assert pseudonymize("install-a", "user-1") != pseudonymize("install-a", "user-2")
