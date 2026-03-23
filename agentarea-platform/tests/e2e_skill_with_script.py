#!/usr/bin/env python3
"""End-to-end test: Skill with bundled script execution.

Demonstrates the full flow:
  1. Skill has a bundled calculator.py file
  2. Agent sees only skill catalog (name + description) in system prompt
  3. Agent activates the skill → gets instructions + file list
  4. Agent calls run_skill_script to execute calculator.py with arguments
  5. Script runs in a subprocess sandbox and returns the result

Usage:
    cd agentarea-platform
    uv run python tests/e2e_skill_with_script.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, "..", "..", ".env.local"))

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest
from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL = "meta-llama/llama-3.3-70b-instruct"
MAX_ITERATIONS = 10

if not OPENROUTER_API_KEY:
    print("ERROR: OPENROUTER_API_KEY not set in .env.local")
    sys.exit(1)

# ── Skill-bundled scripts (in real platform these live in S3) ───────────
SKILL_SCRIPTS = {
    "calculator-skill": {
        "calculator.py": '''\
"""Calculator script bundled with the calculator-skill.

Usage: python calculator.py <expression>
Example: python calculator.py "42 * 17"
"""
import sys

if len(sys.argv) < 2:
    print("Error: pass an expression as argument")
    sys.exit(1)

expression = sys.argv[1]

# Safe eval — only allow math operations
allowed = set("0123456789+-*/.() ")
if not all(c in allowed for c in expression):
    print(f"Error: unsafe expression '{expression}'")
    sys.exit(1)

result = eval(expression)
print(f"{expression} = {result}")
''',
    },
    "data-analyzer-skill": {
        "analyze.js": '''\
// Data analyzer script bundled with the data-analyzer-skill
const data = JSON.parse(process.argv[2] || "[]");
console.log("Mean:", data.reduce((a, b) => a + b, 0) / data.length);
''',
    },
}

# ── Skill definitions ───────────────────────────────────────────────────
SKILLS = [
    SkillEntry(
        name="calculator-skill",
        description="Run mathematical calculations via a Python script",
        content="""\
This skill provides a Python calculator script.

To use it:
1. Call the `run_skill_script` tool
2. Set `skill_name` to "calculator-skill"
3. Set `script_name` to "calculator.py"
4. Set `args` to the math expression, e.g. "42 * 17"

The script evaluates the expression safely and returns the result.""",
        files=["calculator.py"],
    ),
    SkillEntry(
        name="data-analyzer-skill",
        description="Analyze datasets using a JavaScript script (mean, median, etc.)",
        content="""\
This skill provides a JavaScript data analysis script.

To use it:
1. Call `run_skill_script` with skill_name="data-analyzer-skill"
2. Set script_name to "analyze.js"
3. Pass your JSON data array as args.""",
        files=["analyze.js"],
    ),
]

# ── Tool definitions ────────────────────────────────────────────────────
RUN_SKILL_SCRIPT_TOOL = {
    "type": "function",
    "function": {
        "name": "run_skill_script",
        "description": (
            "Execute a script bundled with an activated skill. "
            "The skill must be activated first via activate_skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the activated skill that owns the script",
                },
                "script_name": {
                    "type": "string",
                    "description": "Filename of the script to run (e.g. calculator.py)",
                },
                "args": {
                    "type": "string",
                    "description": "Arguments to pass to the script",
                },
            },
            "required": ["skill_name", "script_name"],
        },
    },
}

COMPLETION_TOOL = {
    "type": "function",
    "function": {
        "name": "completion",
        "description": "Signal that the task is complete with the final result",
        "parameters": {
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "Final result"},
            },
            "required": ["result"],
        },
    },
}


def execute_skill_script(
    skill_name: str,
    script_name: str,
    args: str,
    activated_skills: set[str],
) -> str:
    """Execute a skill-bundled script in a subprocess sandbox."""
    # Guard: skill must be activated first
    if skill_name not in activated_skills:
        return f"Error: skill '{skill_name}' has not been activated. Call activate_skill first."

    # Resolve script content
    scripts = SKILL_SCRIPTS.get(skill_name, {})
    script_content = scripts.get(script_name)
    if not script_content:
        available = list(scripts.keys()) if scripts else []
        return f"Error: script '{script_name}' not found in skill '{skill_name}'. Available: {available}"

    # Determine interpreter
    if script_name.endswith(".py"):
        interpreter = [sys.executable]
    elif script_name.endswith(".js"):
        interpreter = ["node"]
    else:
        return f"Error: unsupported script type: {script_name}"

    # Write to temp file and execute in subprocess (sandbox)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=os.path.splitext(script_name)[1], delete=False
    ) as f:
        f.write(script_content)
        f.flush()
        try:
            cmd = interpreter + [f.name]
            if args:
                cmd.append(args)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                output += f"\nSTDERR: {result.stderr.strip()}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: script timed out (10s limit)"
        except FileNotFoundError as e:
            return f"Error: interpreter not found: {e}"
        finally:
            os.unlink(f.name)


async def main():
    print("=" * 60)
    print("E2E Test: Skill with Bundled Script Execution")
    print(f"Model: {MODEL} via OpenRouter")
    print("=" * 60)

    llm = LLMModel(
        provider_type="openrouter",
        model_name=MODEL,
        api_key=OPENROUTER_API_KEY,
    )

    # Build skill catalog + activation tool
    registry = SkillCatalogBuilder.build_registry(SKILLS)
    skill_tool = SkillActivationTool(registry)
    catalog_text = SkillCatalogBuilder.build_catalog(SKILLS)

    tools = [
        skill_tool.get_openai_function_definition(),
        RUN_SKILL_SCRIPT_TOOL,
        COMPLETION_TOOL,
    ]

    system_prompt = f"""You are a helpful AI agent with access to skills that bundle executable scripts.

WORKFLOW:
1. Check the Available Skills catalog below
2. When a task matches a skill, call `activate_skill` to load its instructions
3. Follow the instructions to call `run_skill_script` with the correct script
4. Report the result via `completion`

IMPORTANT: You MUST activate a skill before running its scripts.
{catalog_text}"""

    task = "Calculate 42 * 17 + 99 using the calculator skill."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    print(f"\nTask: {task}")
    print(f"System prompt tokens (est): ~{len(system_prompt) // 4}")
    print(f"Skills in catalog: {len(SKILLS)} (names + descriptions only)")
    print(f"Full content NOT in prompt (saved ~{sum(len(s.content) for s in SKILLS) // 4} tokens)")
    print()

    # ── Agent Loop ──────────────────────────────────────────────
    completed = False
    script_executed = False

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"── Iteration {iteration} ──")

        request = LLMRequest(messages=messages, tools=tools, temperature=0.1)
        response = await llm.complete(request)

        if response.content:
            print(f"  Assistant: {response.content[:200]}")

        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant_msg["tool_calls"] = response.tool_calls
        messages.append(assistant_msg)

        if not response.tool_calls:
            print("  (no tool calls — ending)")
            break

        for tc in response.tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}
            tc_id = tc.get("id", f"call_{iteration}")

            if fn_name == "activate_skill":
                skill_name = fn_args.get("skill_name", "")
                print(f"  >> activate_skill('{skill_name}')")
                result = await skill_tool.execute(**fn_args)
                result_text = result.get("result", "")
                print(f"     Loaded {len(result_text)} chars of instructions + file list")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": "activate_skill",
                    "content": result_text,
                })

            elif fn_name == "run_skill_script":
                sn = fn_args.get("skill_name", "")
                script = fn_args.get("script_name", "")
                args = fn_args.get("args", "")
                print(f"  >> run_skill_script('{sn}', '{script}', '{args}')")
                output = execute_skill_script(
                    sn, script, args, skill_tool.activated_skills
                )
                print(f"     Output: {output}")
                script_executed = "Error" not in output
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": "run_skill_script",
                    "content": output,
                })

            elif fn_name == "completion":
                result_text = fn_args.get("result", "Done")
                print(f"\n  COMPLETED: {result_text}")
                completed = True
                break

            else:
                print(f"  >> Unknown tool: {fn_name}")
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
    print(f"Iterations: {iteration}")
    print(f"Skills activated: {skill_tool.activated_skills or 'none'}")

    passed = 0
    total = 5

    if "calculator-skill" in skill_tool.activated_skills:
        print("\n  PASS: calculator-skill activated")
        passed += 1
    else:
        print("\n  FAIL: calculator-skill NOT activated")

    if "data-analyzer-skill" not in skill_tool.activated_skills:
        print("  PASS: data-analyzer-skill NOT activated (correctly skipped)")
        passed += 1
    else:
        print("  FAIL: data-analyzer-skill was activated (unnecessary)")

    if script_executed:
        print("  PASS: calculator.py script was executed successfully")
        passed += 1
    else:
        print("  FAIL: calculator.py script was NOT executed")

    if completed:
        print("  PASS: Task completed")
        passed += 1
    else:
        print("  FAIL: Task did not complete")

    # Check that the answer is correct (42*17+99 = 813)
    final_msgs = [m for m in messages if m.get("role") == "tool" and "= " in m.get("content", "")]
    correct_answer = any("813" in m["content"] for m in final_msgs)
    if correct_answer:
        print("  PASS: Correct answer (813) computed by script")
        passed += 1
    else:
        print("  FAIL: Answer 813 not found in script output")

    print(f"\n  Score: {passed}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
