

import asyncio
import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from groq import Groq  # type: ignore[import]
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logger import StepTracker, get_logger, log_event
from memory import SessionMemory

logger = get_logger()


def _mcp_tool_to_groq(tool: Any) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }



PLANNING_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an autonomous AI agent with access to tools for generating employee
    CSV data, importing it into LibreOffice Calc, and uploading it to Google Sheets.

    PLANNING PHASE — Do NOT call any tools yet.
    Output a JSON array of planned steps. Each step must have:
      - "step_name": short human-readable label
      - "tool": exact tool name to call
      - "arguments": dict of arguments to pass

    Example output:
    [
      {"step_name": "Generate CSV", "tool": "generate_employee_csv", "arguments": {"num_rows": 20}},
      {"step_name": "Import to LibreOffice", "tool": "import_csv_to_libreoffice", "arguments": {"csv_path": "<use result from step 1>", "output_format": "xlsx"}},
      {"step_name": "Import to Google Sheets", "tool": "import_csv_to_google_sheets", "arguments": {"csv_path": "<use result from step 1>"}}
    ]

    IMPORTANT: Output ONLY the JSON array — no explanation, no markdown fences.
    Use "<use result from step N>" as a placeholder when a later step needs
    the output of an earlier step.
""")

EXECUTION_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an autonomous AI agent executing a pre-approved plan step by step.
    Call exactly one tool per response. Use the tool results to fill in any
    placeholder values from the plan. If a step fails, note it and continue
    with the remaining steps unless they strictly depend on the failed one.
    When all steps are done, respond with a plain-text summary — no tool call.
""")


def _extract_json_plan(text: str) -> List[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


class Planner:

    def __init__(self, memory: Optional[SessionMemory] = None) -> None:
        from config import GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL  # lazy import

        self.groq = Groq(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
        self.model = GROQ_MODEL
        self.memory = memory or SessionMemory()
        self.tracker = StepTracker()


    async def run(self, prompt: str) -> StepTracker:
        server_path = Path(__file__).parent / "mcp_server.py"
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_path)],
            env=None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await self._run_with_session(session, prompt)

        return self.tracker

    async def _run_with_session(
        self, session: ClientSession, prompt: str
    ) -> StepTracker:
        self.memory.set_prompt(prompt)
        log_event(f"User prompt: {prompt!r}", tool="planner", status="received")

        tools_info = await session.list_tools()
        groq_tools = [_mcp_tool_to_groq(t) for t in tools_info.tools]
        log_event(
            f"Discovered {len(groq_tools)} tools: "
            f"{[t['function']['name'] for t in groq_tools]}",
            tool="planner",
            status="ready",
        )

        plan = await self._plan(prompt, groq_tools)
        self.memory.set_plan(plan)
        self._print_plan(plan)

        await self._execute(session, plan, groq_tools, prompt)

        return self.tracker

    async def _plan(
        self, prompt: str, groq_tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        log_event("Starting planning phase…", tool="planner", status="planning")

        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        response = self.groq.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
        )
        raw = response.choices[0].message.content or "[]"
        try:
            plan = _extract_json_plan(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            log_event(
                f"Could not parse plan JSON ({exc}); falling back to default plan.",
                tool="planner",
                status="warning",
                level="warning",
            )
            plan = self._default_plan()

        return plan

    def _default_plan(self) -> List[Dict[str, Any]]:
        return [
            {
                "step_name": "Generate Employee CSV",
                "tool": "generate_employee_csv",
                "arguments": {"num_rows": 20},
            },
            {
                "step_name": "Import CSV to LibreOffice",
                "tool": "import_csv_to_libreoffice",
                "arguments": {"csv_path": "__csv_path__", "output_format": "xlsx"},
            },
            {
                "step_name": "Import CSV to Google Sheets",
                "tool": "import_csv_to_google_sheets",
                "arguments": {"csv_path": "__csv_path__"},
            },
        ]

    def _print_plan(self, plan: List[Dict[str, Any]]) -> None:
        print("\n" + "=" * 60)
        print("  EXECUTION PLAN")
        print("=" * 60)
        for i, step in enumerate(plan, 1):
            print(f"  Step {i}: {step.get('step_name', '?')}")
            print(f"           Tool: {step.get('tool', '?')}")
            args_str = json.dumps(step.get("arguments", {}), indent=None)
            print(f"           Args: {args_str}")
        print("=" * 60 + "\n")

    async def _execute(
        self,
        session: ClientSession,
        plan: List[Dict[str, Any]],
        groq_tools: List[Dict[str, Any]],
        original_prompt: str,
    ) -> None:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": EXECUTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Execute this plan step by step:\n"
                    f"{json.dumps(plan, indent=2)}\n\n"
                    f"Original instruction: {original_prompt}"
                ),
            },
        ]

        for step_idx, step in enumerate(plan):
            step_name = step.get("step_name", f"Step {step_idx + 1}")
            tool_name = step.get("tool", "")
            planned_args = step.get("arguments", {})

            log_event(
                f"Asking Groq to execute step {step_idx + 1}: {step_name}",
                tool="planner",
                status="executing",
            )

            response = self.groq.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=groq_tools,
                tool_choice="required",
                temperature=0.0,
            )

            assistant_msg = response.choices[0].message
            messages.append(assistant_msg.model_dump(exclude_none=True))

            if not assistant_msg.tool_calls:
                result = {
                    "success": False,
                    "message": "Groq did not issue a tool call for this step.",
                    "data": None,
                }
                self.tracker.start(step_name, tool_name)
                self.tracker.finish(step_name, tool_name, result)
                self.memory.add_step_result(step_name, tool_name, result)
                messages.append(
                    {"role": "user", "content": f"Step '{step_name}' was skipped."}
                )
                continue

            tool_call = assistant_msg.tool_calls[0]
            actual_tool_name = tool_call.function.name
            try:
                actual_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                actual_args = {}

            self.tracker.start(step_name, actual_tool_name)
            log_event(
                f"Calling tool '{actual_tool_name}' with args: {actual_args}",
                tool=actual_tool_name,
                status="calling",
            )

            try:
                mcp_result = await session.call_tool(actual_tool_name, actual_args)
                raw_content = (
                    mcp_result.content[0].text
                    if mcp_result.content
                    else "{}"
                )
                try:
                    result = json.loads(raw_content)
                except (json.JSONDecodeError, TypeError):
                    result = {
                        "success": True,
                        "message": str(raw_content),
                        "data": None,
                    }
            except Exception as exc:  # noqa: BLE001
                result = {
                    "success": False,
                    "message": f"MCP tool call failed: {exc}",
                    "data": None,
                }

            self.tracker.finish(step_name, actual_tool_name, result)
            self.memory.add_step_result(step_name, actual_tool_name, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

        log_event("Execution phase complete.", tool="planner", status="done")


def run_sync(prompt: str, memory: Optional[SessionMemory] = None) -> StepTracker:
    planner = Planner(memory=memory)
    return asyncio.run(planner.run(prompt))
