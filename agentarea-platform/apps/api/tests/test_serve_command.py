"""How the API server is started, since prod runs exactly this command.

The image is `CMD ["agentarea-api", "serve"]` and the chart overrides neither
command nor args, so every default here is a production default.
"""

from unittest.mock import patch

from agentarea_api.cli import serve
from click.testing import CliRunner


def _run(args=None, env=None):
    with patch("agentarea_api.cli.uvicorn.run") as run:
        result = CliRunner().invoke(serve, args or [], env=env or {})
        assert result.exit_code == 0, result.output
        return run.call_args.kwargs


def test_shutdown_waits_a_bounded_time_for_open_connections():
    """Unbounded meant every rollout ended in SIGKILL.

    The API serves SSE (`text/event-stream`), and those connections do not end
    on their own. Waiting for all connections to close therefore never
    completed: the pod sat until its termination grace period ran out and was
    killed, dropping whatever else was still in flight.
    """
    timeout = _run()["timeout_graceful_shutdown"]

    assert timeout is not None
    assert 0 < timeout <= 30


def test_reload_is_off_unless_asked():
    assert _run()["reload"] is False


def test_one_worker_by_default():
    """One process, one event loop. Capacity comes from replicas."""
    assert _run()["workers"] == 1


def test_workers_can_be_raised_without_rebuilding_the_image():
    """So a pod given more than one CPU can actually use them."""
    assert _run(env={"AGENTAREA_API_WORKERS": "2"})["workers"] == 2


def test_reload_forces_a_single_worker():
    """uvicorn cannot reload across a worker pool."""
    assert _run(["--reload"], env={"AGENTAREA_API_WORKERS": "4"})["workers"] == 1
