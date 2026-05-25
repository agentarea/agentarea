"""Unit tests for ContextStore with mocked S3."""

import json
from unittest.mock import MagicMock, patch

import pytest
from agentarea_execution.workflows.context_store import ContextStore


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client."""
    client = MagicMock()
    client.exceptions = MagicMock()
    client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
    return client


@pytest.fixture
def mock_aws_settings():
    settings = MagicMock()
    settings.S3_BUCKET_NAME = "test-bucket"
    return settings


@pytest.fixture
def store(mock_s3_client, mock_aws_settings):
    """Create a ContextStore with mocked dependencies."""
    with patch(
        "agentarea_execution.workflows.context_store.ContextStore.client",
        new_callable=lambda: property(lambda self: mock_s3_client),
    ), patch(
        "agentarea_execution.workflows.context_store.ContextStore.bucket",
        new_callable=lambda: property(lambda self: "test-bucket"),
    ):
        s = ContextStore(workspace_id="ws-1", task_id="task-1")
        s._client = mock_s3_client
        s._settings = mock_aws_settings
        return s


class TestStoreOutput:
    @pytest.mark.asyncio
    async def test_stores_to_correct_key(self, store, mock_s3_client):
        await store.store_output("out-123", "hello world")

        mock_s3_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="tasks/ws-1/task-1/outputs/out-123.json",
            Body=b"hello world",
            ContentType="application/json",
        )


class TestReadOutput:
    def _setup_get_object(self, mock_s3_client, content: str):
        body = MagicMock()
        body.read.return_value = content.encode("utf-8")
        mock_s3_client.get_object.return_value = {"Body": body}

    @pytest.mark.asyncio
    async def test_reads_full_content(self, store, mock_s3_client):
        self._setup_get_object(mock_s3_client, "line1\nline2\nline3")

        result = await store.read_output("out-123")
        assert result == "line1\nline2\nline3"

    @pytest.mark.asyncio
    async def test_grep_filters_lines(self, store, mock_s3_client):
        self._setup_get_object(mock_s3_client, "error: fail\ninfo: ok\nerror: bad")

        result = await store.read_output("out-123", grep="error")
        assert "error: fail" in result
        assert "error: bad" in result
        assert "info: ok" not in result

    @pytest.mark.asyncio
    async def test_grep_invalid_regex_falls_back_to_literal(self, store, mock_s3_client):
        self._setup_get_object(mock_s3_client, "foo[bar\nbaz\nfoo[bar again")

        result = await store.read_output("out-123", grep="foo[bar")
        assert "foo[bar" in result
        assert "baz" not in result

    @pytest.mark.asyncio
    async def test_head_returns_first_n_lines(self, store, mock_s3_client):
        self._setup_get_object(mock_s3_client, "a\nb\nc\nd\ne")

        result = await store.read_output("out-123", head=2)
        assert result == "a\nb"

    @pytest.mark.asyncio
    async def test_tail_returns_last_n_lines(self, store, mock_s3_client):
        self._setup_get_object(mock_s3_client, "a\nb\nc\nd\ne")

        result = await store.read_output("out-123", tail=2)
        assert result == "d\ne"

    @pytest.mark.asyncio
    async def test_safety_limit_truncates(self, store, mock_s3_client):
        huge = "x" * 20000
        self._setup_get_object(mock_s3_client, huge)

        result = await store.read_output("out-123")
        assert len(result) < 20000
        assert "truncated" in result


class TestStoreHistoryChunk:
    @pytest.mark.asyncio
    async def test_stores_messages_as_json(self, store, mock_s3_client):
        messages = [{"role": "user", "content": "hello"}]
        await store.store_history_chunk(0, messages)

        call_args = mock_s3_client.put_object.call_args
        assert call_args.kwargs["Key"] == "tasks/ws-1/task-1/history/chunk_0.json"
        body = json.loads(call_args.kwargs["Body"].decode("utf-8"))
        assert body == messages


class TestSearchHistory:
    def _setup_history_chunks(self, mock_s3_client, chunks: list[list[dict]]):
        """Setup paginator to return chunk objects and get_object for each."""
        paginator = MagicMock()
        contents = [
            {"Key": f"tasks/ws-1/task-1/history/chunk_{i}.json"}
            for i in range(len(chunks))
        ]
        paginator.paginate.return_value = [{"Contents": contents}]
        mock_s3_client.get_paginator.return_value = paginator

        def get_object_side_effect(**kwargs):
            key = kwargs["Key"]
            idx = int(key.split("chunk_")[1].split(".")[0])
            body = MagicMock()
            body.read.return_value = json.dumps(chunks[idx]).encode("utf-8")
            return {"Body": body}

        mock_s3_client.get_object.side_effect = get_object_side_effect

    @pytest.mark.asyncio
    async def test_search_by_grep(self, store, mock_s3_client):
        self._setup_history_chunks(mock_s3_client, [
            [
                {"role": "user", "content": "find the error"},
                {"role": "tool", "content": "success: ok", "name": "run"},
            ],
        ])

        result = await store.search_history(grep="error")
        assert "find the error" in result
        assert "success: ok" not in result

    @pytest.mark.asyncio
    async def test_search_by_tool_name(self, store, mock_s3_client):
        self._setup_history_chunks(mock_s3_client, [
            [
                {"role": "tool", "content": "result1", "name": "github"},
                {"role": "tool", "content": "result2", "name": "jira"},
            ],
        ])

        result = await store.search_history(tool_name="github")
        assert "result1" in result
        assert "result2" not in result

    @pytest.mark.asyncio
    async def test_no_chunks_returns_message(self, store, mock_s3_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3_client.get_paginator.return_value = paginator

        result = await store.search_history(grep="anything")
        assert "No matching" in result
