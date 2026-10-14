"""/health reports the version of the installed packages, not a string in the source."""

from importlib.metadata import version

from agentarea_api.main import app
from fastapi.testclient import TestClient


def test_health_reports_the_installed_version():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["version"] == version("agentarea-common")
    assert app.version == version("agentarea-common")
