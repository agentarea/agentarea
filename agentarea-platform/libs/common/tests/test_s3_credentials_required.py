"""Object storage credentials are never the built-in defaults where a write must land.

``AWSSettings`` falls back to minioadmin, which against real S3 fails every
write, one by one, while the process carries on. Whatever stores packages asks
first and stops when the deployment gave it none.
"""

import pytest
from agentarea_common.config.aws import ObjectStorageNotConfiguredError, require_s3_credentials


@pytest.fixture(autouse=True)
def _no_s3_env(monkeypatch):
    for name in ("AGENTAREA_S3_ACCESS_KEY", "AGENTAREA_S3_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_unset_credentials_are_refused_by_name():
    with pytest.raises(ObjectStorageNotConfiguredError) as refused:
        require_s3_credentials()

    assert "AGENTAREA_S3_ACCESS_KEY" in str(refused.value)
    assert "AGENTAREA_S3_SECRET_KEY" in str(refused.value)


def test_one_missing_key_is_refused(monkeypatch):
    monkeypatch.setenv("AGENTAREA_S3_ACCESS_KEY", "key")

    with pytest.raises(ObjectStorageNotConfiguredError, match="AGENTAREA_S3_SECRET_KEY"):
        require_s3_credentials()


def test_configured_credentials_pass(monkeypatch):
    monkeypatch.setenv("AGENTAREA_S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("AGENTAREA_S3_SECRET_KEY", "minioadmin")

    require_s3_credentials()
