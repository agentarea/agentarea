#!/usr/bin/env python3
"""Verification script to confirm that the workflow is using the enhanced ReAct framework.
"""

import sys

sys.path.append('core/libs/execution')

from agentarea_execution.workflows.helpers import MessageBuilder


def verify_react_framework():
    """Verify that MessageBuilder is using ReAct framework."""
    print("=== Verifying ReAct Framework Usage ===\n")

    # Sample data similar to what the workflow would use
    agent_name = "TestAgent"
    agent_instruction = "You are a helpful AI assistant specialized in data analysis."
    goal_description = "Analyze the provided dataset and generate insights"
    success_criteria = [
        "Load and validate the dataset",
        "Perform statistical analysis",
        "Generate actionable insights",
        "Create a summary report"
    ]
    available_tools = [
        {
            "type": "function",
            "function": {
                "name": "load_data",
                "description": "Load data from a file or database"
            }
        },
        {
            "name": "analyze_data",  # Old format
            "description": "Perform statistical analysis on data"
        }
    ]

    # Call the same method that the workflow calls
    system_prompt = MessageBuilder.build_system_prompt(
        agent_name=agent_name,
        agent_instruction=agent_instruction,
        goal_description=goal_description,
        success_criteria=success_criteria,
        available_tools=available_tools
    )

    # Check for ReAct framework markers
    react_markers = [
        "ReAct (Reasoning + Acting) framework",
        "**Thought:**",
        "**Observation:**",
        "**Action:**",
        "**Result Analysis:**",
        "MUST follow this exact pattern"
    ]

    print("Checking for ReAct framework markers:")
    all_present = True
    for marker in react_markers:
        present = marker in system_prompt
        status = "✅" if present else "❌"
        print(f"{status} {marker}")
        if not present:
            all_present = False

    print(f"\nReAct Framework Status: {'✅ ACTIVE' if all_present else '❌ NOT ACTIVE'}")

    if all_present:
        print("\n🎉 SUCCESS: The workflow is using the enhanced ReAct framework!")
        print("Agents will now show their reasoning process step-by-step.")
    else:
        print("\n⚠️  WARNING: ReAct framework markers not found in system prompt.")
        print("First 500 characters of prompt:")
        print("-" * 50)
        print(system_prompt[:500] + "...")

    return all_present

def verify_task_completion_handling():
    """Verify that task completion handling improvements are in place."""
    print("\n=== Verifying Task Completion Handling ===\n")

    # Check the workflow file for our modifications
    try:
        with open('core/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py') as f:
            workflow_content = f.read()

        # Check for our specific modifications
        checks = [
            ('task_complete event filtering', 'if tool_name != "task_complete":'),
            ('Internal completion logging', 'INTERNAL: Task completion detected'),
            ('Debug logging for task_complete', 'task_complete tool executed - not publishing as workflow event'),
        ]

        print("Checking for task completion improvements:")
        all_present = True
        for description, pattern in checks:
            present = pattern in workflow_content
            status = "✅" if present else "❌"
            print(f"{status} {description}")
            if not present:
                all_present = False

        print(f"\nTask Completion Handling: {'✅ IMPROVED' if all_present else '❌ NOT IMPROVED'}")
        return all_present

    except FileNotFoundError:
        print("❌ Could not find workflow file")
        return False

def main():
    """Run all verifications."""
    print("Verifying AgentArea Prompt Improvements\n")

    react_ok = verify_react_framework()
    completion_ok = verify_task_completion_handling()

    print("\n" + "="*50)
    print("FINAL VERIFICATION RESULTS")
    print("="*50)

    if react_ok and completion_ok:
        print("🎉 ALL IMPROVEMENTS VERIFIED SUCCESSFULLY!")
        print("✅ ReAct framework is active")
        print("✅ Task completion handling is improved")
        print("\nThe workflow will now:")
        print("- Use structured reasoning with explicit thought processes")
        print("- Handle task completion internally without publishing events")
        print("- Provide better transparency for users")
    else:
        print("⚠️  SOME IMPROVEMENTS NOT VERIFIED")
        if not react_ok:
            print("❌ ReAct framework not active")
        if not completion_ok:
            print("❌ Task completion handling not improved")

if __name__ == "__main__":
    main()
