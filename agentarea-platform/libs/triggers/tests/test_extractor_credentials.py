"""A mailbox password must never reach the plain-JSON extractor config column."""

from agentarea_triggers.extractors import resolves_own_credentials
from agentarea_triggers.extractors.imap import ImapExtractor


def test_imap_declares_that_it_reads_the_secret_store():
    assert resolves_own_credentials("imap") is True
    assert ImapExtractor.resolves_own_credentials is True


def test_an_extractor_that_does_not_declare_it_keeps_the_old_behaviour():
    """Telegram polling still needs its token in the config for the Go poller."""
    assert resolves_own_credentials("telegram_polling") is False


def test_an_unknown_extractor_does_not_claim_to_handle_secrets():
    assert resolves_own_credentials("nothing-registered-here") is False
