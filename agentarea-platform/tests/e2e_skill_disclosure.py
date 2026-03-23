"""End-to-end test: Progressive Skill Disclosure with OpenRouter.

Runs an agent loop using arcee-ai/trinity-large-preview:free via OpenRouter.
The agent has 2 skills but should only activate the one it needs,
then call the tool provided by that skill's instructions.

Usage:
    cd agentarea-platform
    uv run python tests/e2e_skill_disclosure.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

# Load .env.local from monorepo root
_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_script_dir, "..", "..", ".env.local")
load_dotenv(_env_path)

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest
from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry

# ── Config ──────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = "arcee-ai/trinity-large-preview:free"
MAX_ITERATIONS = 10

if not OPENROUTER_API_KEY:
    print("ERROR: OPENROUTER_API_KEY not set in .env.local")
    sys.exit(1)

# ── Skills ──────────────────────────────────────────────────────────────────
# Skill 1: Python data analysis — should be activated for our task
PYTHON_SKILL = SkillEntry(
    name="python-executor",
    description="Execute Python scripts for data analysis, calculations, and file processing",
    content="""You can run Python code using the `run_python` tool.
Use this skill when you need to perform calculations, data analysis, or any programmatic task.
Always use the run_python tool to execute code rather than showing it inline.""",
    files=["analysis_helpers.py"],
)

# Skill 2: JavaScript formatter — should NOT be activated for our task
JS_SKILL = SkillEntry(
    name="js-formatter",
    description="Format and lint JavaScript/TypeScript code using Prettier and ESLint",
    content="""You can format JavaScript code using the `run_js` tool.
Use this for formatting, linting, and beautifying JS/TS source files.""",
    files=["prettier.config.js"],
)

SKILLS = [PYTHON_SKILL, JS_SKILL]

# ── Tool definitions (what the agent can call) ──────────────────────────────
RUN_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Execute a Python script and return its stdout output",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                }
            },
            "required": ["code"],
        },
    },
}

COMPLETION_TOOL = {
    "type": "function",
    "function": {
        "name": "completion",
        "description": "Signal that the task is complete",
        "parameters": {
            "type": "object",
            "properties": {
                "result": {
                    "type": "string",
                    "description": "Final result summary",
                }
            },
            "required": ["result"],
        },
    },
}


def execute_python(code: str) -> str:
    """Actually run Python code in a subprocess."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        try:
            result = subprocess.run(
                [sys.executable, f.name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout
            if result.returncode != 0:
                output += f"\nSTDERR: {result.stderr}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "ERROR: Script timed out after 30s"
        finally:
            os.unlink(f.name)


async def main():
    print("=" * 60)
    print("E2E Test: Progressive Skill Disclosure")
    print(f"Model: {MODEL} via OpenRouter")
    print("=" * 60)

    # ── Setup ───────────────────────────────────────────────────
    llm = LLMModel(
        provider_type="openrouter",
        model_name=MODEL,
        api_key=OPENROUTER_API_KEY,
    )

    # Build skill catalog + activation tool
    registry = SkillCatalogBuilder.build_registry(SKILLS)
    skill_tool = SkillActivationTool(registry)
    catalog_text = SkillCatalogBuilder.build_catalog(SKILLS)

    # Tools available to the agent
    tools = [
        skill_tool.get_openai_function_definition(),
        RUN_PYTHON_TOOL,
        COMPLETION_TOOL,
    ]

    system_prompt = f"""You are a helpful AI agent. You have access to skills that provide specialized instructions.
When a task matches a skill's description, FIRST use the activate_skill tool to load its instructions, then follow them.
{catalog_text}

IMPORTANT: You must use the activate_skill tool before using any skill-specific tools.
When done, call the completion tool with your result."""

    task = "Calculate the first 10 Fibonacci numbers and their sum using Python."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    print(f"\nTask: {task}")
    print(f"\nSystem prompt tokens (estimate): ~{len(system_prompt) // 4}")
    print(f"Skills in catalog: {len(SKILLS)} (names+descriptions only)")
    print(f"Full skill content NOT in prompt (saved ~{sum(len(s.content) for s in SKILLS) // 4} tokens)")
    print()

    # ── Agent Loop ──────────────────────────────────────────────
    completed = False
    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"── Iteration {iteration} ──")

        request = LLMRequest(messages=messages, tools=tools, temperature=0.1)
        response = await llm.complete(request)

        print(f"  Assistant: {response.content[:200] if response.content else '(no text)'}")

        # Add assistant message
        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant_msg["tool_calls"] = response.tool_calls
        messages.append(assistant_msg)

        if not response.tool_calls:
            print("  (no tool calls — ending)")
            break

        # Process tool calls
        for tc in response.tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            tc_id = tc.get("id", f"call_{iteration}")
            print(f"  Tool call: {fn_name}({json.dumps(fn_args)[:100]})")

            if fn_name == "activate_skill":
                # Execute skill activation
                result = await skill_tool.execute(**fn_args)
                result_text = result.get("result", "")
                print(f"  → Skill '{fn_args.get('skill_name')}' activated! ({len(result_text)} chars)")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": "activate_skill",
                    "content": result_text,
                })

            elif fn_name == "run_python":
                code = fn_args.get("code", "")
                print(f"  → Running Python code ({len(code)} chars)...")
                output = execute_python(code)
                print(f"  → Output: {output.strip()[:200]}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": "run_python",
                    "content": output,
                })

            elif fn_name == "completion":
                result_text = fn_args.get("result", "Done")
                print(f"\n  COMPLETED: {result_text}")
                completed = True
                break

            else:
                print(f"  → Unknown tool: {fn_name}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": f"Unknown tool: {fn_name}",
                })

        if completed:
            break

    # ── Results ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Iterations used: {iteration}")
    print(f"Skills activated: {skill_tool.activated_skills or 'none'}")
    print(f"Completed: {completed}")

    # Verify progressive disclosure worked
    activated = skill_tool.activated_skills
    if "python-executor" in activated:
        print("\n✓ PASS: Agent activated python-executor skill (correct)")
    else:
        print("\n✗ FAIL: Agent did NOT activate python-executor skill")

    if "js-formatter" not in activated:
        print("✓ PASS: Agent did NOT activate js-formatter skill (correct — not needed)")
    else:
        print("✗ FAIL: Agent activated js-formatter skill (unnecessary)")

    if completed:
        print("✓ PASS: Agent completed the task")
    else:
        print("✗ FAIL: Agent did not complete the task")


if __name__ == "__main__":
    asyncio.run(main())
