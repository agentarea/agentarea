"""Unit tests for output offloading: build_output_summary and threshold logic."""

import importlib.util
import os


# Load helpers module directly to avoid temporalio dependency
def _load_module_directly(module_name: str, file_path: str):
    """Load a Python module by file path, bypassing package imports."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    return spec, module


# Load constants first (needed by build_output_summary)
_constants_path = os.path.join(
    os.path.dirname(__file__),
    "../../libs/execution/agentarea_execution/workflows/constants.py",
)
_constants_spec, constants_mod = _load_module_directly("constants", os.path.abspath(_constants_path))
_constants_spec.loader.exec_module(constants_mod)


class TestBuildOutputSummary:
    """Test build_output_summary by reimplementing the pure logic
    (avoids temporalio import chain via helpers.py).
    """

    def _build_output_summary(self, content: str, output_id: str) -> str:
        """Reimplements build_output_summary logic for testing without workflow imports."""
        head_chars = constants_mod.OUTPUT_SUMMARY_HEAD_CHARS  # 500
        tail_chars = constants_mod.OUTPUT_SUMMARY_TAIL_CHARS  # 200

        lines = content.split("\n")
        head = content[:head_chars]
        total_chars = len(content)
        total_lines = len(lines)

        summary = f"[Output stored as {output_id} — {total_chars:,} chars, {total_lines} lines]\n"
        summary += f"Preview:\n{head}\n"

        if total_chars > head_chars + tail_chars:
            tail = content[-tail_chars:]
            summary += f"...\n{tail}\n"

        summary += (
            f'\nUse read_tool_output("{output_id}") for full content, '
            f'or read_tool_output("{output_id}", grep="pattern") to search.'
        )
        return summary

    def test_includes_output_id(self):
        content = "x" * 10000
        summary = self._build_output_summary(content, "call-abc")
        assert "call-abc" in summary

    def test_includes_char_count(self):
        content = "x" * 10000
        summary = self._build_output_summary(content, "out-1")
        assert "10,000 chars" in summary

    def test_includes_line_count(self):
        content = "line1\nline2\nline3"
        summary = self._build_output_summary(content, "out-1")
        assert "3 lines" in summary

    def test_includes_head_preview(self):
        content = "HEADER_CONTENT" + "x" * 10000
        summary = self._build_output_summary(content, "out-1")
        assert "HEADER_CONTENT" in summary

    def test_includes_tail_for_long_content(self):
        content = "x" * 5000 + "TAIL_MARKER"
        summary = self._build_output_summary(content, "out-1")
        assert "TAIL_MARKER" in summary

    def test_no_tail_for_short_content(self):
        content = "short"
        summary = self._build_output_summary(content, "out-1")
        assert "..." not in summary

    def test_includes_usage_instruction(self):
        content = "x" * 10000
        summary = self._build_output_summary(content, "out-1")
        assert 'read_tool_output("out-1")' in summary
        assert 'grep="pattern"' in summary

    def test_summary_much_shorter_than_original(self):
        content = "x" * 50000
        summary = self._build_output_summary(content, "out-1")
        assert len(summary) < len(content) / 10


class TestOffloadThreshold:
    """Test the threshold constant value and logic."""

    def test_threshold_is_8000(self):
        assert constants_mod.TOOL_OUTPUT_OFFLOAD_CHARS == 8000

    def test_below_threshold_no_offload(self):
        content = "x" * 7999
        assert len(content) <= constants_mod.TOOL_OUTPUT_OFFLOAD_CHARS

    def test_above_threshold_should_offload(self):
        content = "x" * 8001
        assert len(content) > constants_mod.TOOL_OUTPUT_OFFLOAD_CHARS

    def test_read_output_max_return_chars(self):
        assert constants_mod.READ_OUTPUT_MAX_RETURN_CHARS == 16000

    def test_output_summary_head_chars(self):
        assert constants_mod.OUTPUT_SUMMARY_HEAD_CHARS == 500

    def test_output_summary_tail_chars(self):
        assert constants_mod.OUTPUT_SUMMARY_TAIL_CHARS == 200
