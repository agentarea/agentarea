"""How /v1/bundles/install answers a bundle it cannot install."""

import pytest
from agentarea_api.api.v1.bundles import InstallRequest, install_bundle
from agentarea_bundles.application.installer import BundleInstallError, BundleValidationError
from agentarea_bundles.schemas.bundle import Bundle
from fastapi import HTTPException


class _Refusing:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def install(self, bundle, setup_values):
        raise self.exc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (BundleValidationError("skill 'sk' is not a valid SKILL.md: bad"), 422),
        (BundleInstallError("failed to import skill 'sk' from https://github.com/o/r"), 400),
    ],
)
async def test_an_invalid_bundle_is_422_and_a_failed_install_is_400(exc, status):
    body = InstallRequest(bundle=Bundle(name="b"))

    with pytest.raises(HTTPException) as refused:
        await install_bundle(body, _Refusing(exc))  # type: ignore[arg-type]

    assert refused.value.status_code == status
    assert refused.value.detail["message"] == str(exc)
