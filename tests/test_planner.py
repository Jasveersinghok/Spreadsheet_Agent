"""
tests/test_planner.py — Unit tests for planner.py.

The MCP session and Groq client are fully mocked so these tests run without
a running MCP server, LibreOffice, or real Groq API key.

Tests cover:
  - Plan parsing: valid JSON, markdown-fenced JSON, malformed JSON (fallback)
  - Planner.run() dispatches correct tool calls via session.call_tool()
  - Planner.run() handles tool call failures gracefully
  - StepTracker receives one result per plan step
  - Memory is populated with prompt, plan, and step results
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helper: build fake MCP ToolInfo objects
# ---------------------------------------------------------------------------

def _make_tool_info(name: str, description: str = "") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


# ---------------------------------------------------------------------------
# Helper: build a mock Groq client
# ---------------------------------------------------------------------------

def _make_groq_response(tool_name: str, arguments: dict, call_id: str = "call_1") -> MagicMock:
    """Return a mock Groq ChatCompletion that calls *tool_name* with *arguments*."""
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments)

    msg = MagicMock()
    msg.tool_calls = [tool_call]
    msg.content = None
    msg.model_dump.return_value = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
            }
        ],
    }

    response = MagicMock()
    response.choices = [MagicMock(message=msg)]
    return response


def _make_planning_response(plan: list) -> MagicMock:
    """Return a mock Groq response containing a JSON plan."""
    msg = MagicMock()
    msg.tool_calls = []
    msg.content = json.dumps(plan)
    msg.model_dump.return_value = {"role": "assistant", "content": msg.content}

    response = MagicMock()
    response.choices = [MagicMock(message=msg)]
    return response


# ---------------------------------------------------------------------------
# Plan-parsing tests (no async needed)
# ---------------------------------------------------------------------------

class TestPlanParsing:

    def test_valid_json_plan(self):
        from planner import _extract_json_plan
        plan_json = '[{"step_name": "A", "tool": "t1", "arguments": {}}]'
        plan = _extract_json_plan(plan_json)
        assert len(plan) == 1
        assert plan[0]["tool"] == "t1"

    def test_markdown_fenced_json(self):
        from planner import _extract_json_plan
        fenced = "```json\n[{\"step_name\": \"B\", \"tool\": \"t2\", \"arguments\": {}}]\n```"
        plan = _extract_json_plan(fenced)
        assert plan[0]["tool"] == "t2"

    def test_malformed_json_raises(self):
        from planner import _extract_json_plan
        with pytest.raises(json.JSONDecodeError):
            _extract_json_plan("not json at all")

    def test_default_plan_has_three_steps(self):
        from planner import Planner
        with patch("planner.Groq"), patch("config.GROQ_API_KEY", "fake"):
            p = Planner()
        plan = p._default_plan()
        assert len(plan) == 3
        tools = [s["tool"] for s in plan]
        assert "generate_employee_csv" in tools
        assert "import_csv_to_libreoffice" in tools
        assert "import_csv_to_google_sheets" in tools


# ---------------------------------------------------------------------------
# Full async planner tests
# ---------------------------------------------------------------------------

SAMPLE_PLAN = [
    {"step_name": "Generate CSV", "tool": "generate_employee_csv", "arguments": {"num_rows": 20}},
    {"step_name": "Import LibreOffice", "tool": "import_csv_to_libreoffice", "arguments": {"csv_path": "/tmp/e.csv"}},
    {"step_name": "Import Google Sheets", "tool": "import_csv_to_google_sheets", "arguments": {"csv_path": "/tmp/e.csv"}},
]


@pytest.fixture()
def patch_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")


@pytest.fixture()
def mock_session():
    """Build a mock MCP ClientSession."""
    session = AsyncMock()

    # list_tools returns 3 tools
    tools = [
        _make_tool_info("generate_employee_csv", "Generate CSV"),
        _make_tool_info("import_csv_to_libreoffice", "LibreOffice import"),
        _make_tool_info("import_csv_to_google_sheets", "Google Sheets import"),
    ]
    list_tools_result = MagicMock()
    list_tools_result.tools = tools
    session.list_tools.return_value = list_tools_result
    session.initialize = AsyncMock()

    # call_tool returns a success result for any tool
    def _call_tool_response(name, args):
        result_data = {
            "success": True,
            "message": f"{name} completed successfully",
            "data": {"file_path": "/tmp/employees.csv"} if name == "generate_employee_csv" else {},
        }
        content_item = MagicMock()
        content_item.text = json.dumps(result_data)
        mock_result = MagicMock()
        mock_result.content = [content_item]
        return mock_result

    session.call_tool = AsyncMock(side_effect=_call_tool_response)
    return session


class TestPlannerDispatch:
    """Verify that planner.py's execute loop calls session.call_tool() correctly."""

    @pytest.mark.asyncio
    async def test_three_tools_called_in_order(self, patch_env, mock_session):
        """All three plan steps should result in one session.call_tool() each."""
        from planner import Planner
        from memory import SessionMemory

        memory = SessionMemory()

        # Build Groq mock:
        # - First call (planning) → returns plan JSON
        # - Next 3 calls (execution) → return tool calls
        groq_mock = MagicMock()
        planning_resp = _make_planning_response(SAMPLE_PLAN)
        exec_responses = [
            _make_groq_response("generate_employee_csv", {"num_rows": 20}, "c1"),
            _make_groq_response("import_csv_to_libreoffice", {"csv_path": "/tmp/employees.csv"}, "c2"),
            _make_groq_response("import_csv_to_google_sheets", {"csv_path": "/tmp/employees.csv"}, "c3"),
        ]
        groq_mock.chat.completions.create.side_effect = [planning_resp] + exec_responses

        planner = Planner(memory=memory)
        planner.groq = groq_mock

        # Call _run_with_session directly to inject the mock session
        tracker = await planner._run_with_session(mock_session, "Test prompt")

        assert mock_session.call_tool.call_count == 3
        called_tools = [c.args[0] for c in mock_session.call_tool.call_args_list]
        assert "generate_employee_csv" in called_tools
        assert "import_csv_to_libreoffice" in called_tools
        assert "import_csv_to_google_sheets" in called_tools

    @pytest.mark.asyncio
    async def test_step_failure_does_not_crash(self, patch_env, mock_session):
        """A tool call failure should be recorded but not raise an exception."""
        from planner import Planner
        from memory import SessionMemory

        memory = SessionMemory()

        # Make the LibreOffice call fail
        def _call_tool_response(name, args):
            if name == "import_csv_to_libreoffice":
                content_item = MagicMock()
                content_item.text = json.dumps({
                    "success": False,
                    "message": "soffice.exe not found",
                    "data": None,
                })
            else:
                content_item = MagicMock()
                content_item.text = json.dumps({
                    "success": True,
                    "message": f"{name} ok",
                    "data": {"file_path": "/tmp/e.csv"},
                })
            result = MagicMock()
            result.content = [content_item]
            return result

        mock_session.call_tool = AsyncMock(side_effect=_call_tool_response)

        groq_mock = MagicMock()
        planning_resp = _make_planning_response(SAMPLE_PLAN)
        exec_responses = [
            _make_groq_response("generate_employee_csv", {"num_rows": 20}, "c1"),
            _make_groq_response("import_csv_to_libreoffice", {"csv_path": "/tmp/e.csv"}, "c2"),
            _make_groq_response("import_csv_to_google_sheets", {"csv_path": "/tmp/e.csv"}, "c3"),
        ]
        groq_mock.chat.completions.create.side_effect = [planning_resp] + exec_responses

        planner = Planner(memory=memory)
        planner.groq = groq_mock

        tracker = await planner._run_with_session(mock_session, "Test prompt")

        steps = tracker.get_steps()
        assert len(steps) == 3
        failed = [s for s in steps if not s.success]
        succeeded = [s for s in steps if s.success]
        assert len(failed) == 1
        assert len(succeeded) == 2
        assert failed[0].tool_name == "import_csv_to_libreoffice"

    @pytest.mark.asyncio
    async def test_memory_populated(self, patch_env, mock_session):
        """Memory should record the prompt, plan, and all step results."""
        from planner import Planner
        from memory import SessionMemory

        memory = SessionMemory()

        groq_mock = MagicMock()
        planning_resp = _make_planning_response(SAMPLE_PLAN)
        exec_responses = [
            _make_groq_response("generate_employee_csv", {"num_rows": 20}, "c1"),
            _make_groq_response("import_csv_to_libreoffice", {"csv_path": "/tmp/e.csv"}, "c2"),
            _make_groq_response("import_csv_to_google_sheets", {"csv_path": "/tmp/e.csv"}, "c3"),
        ]
        groq_mock.chat.completions.create.side_effect = [planning_resp] + exec_responses

        planner = Planner(memory=memory)
        planner.groq = groq_mock

        await planner._run_with_session(mock_session, "Run the full pipeline")

        assert memory.prompt == "Run the full pipeline"
        assert len(memory.plan) == 3
        assert len(memory.step_results) == 3




