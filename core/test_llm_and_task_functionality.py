#!/usr/bin/env python3
"""
Comprehensive test script for LLM configuration and task functionality.
This script demonstrates:
1. LLM model management (list, create, show, test)
2. Agent creation with LLM models
3. Task sending to agents using both agent subcommand and global --agent option
"""

import subprocess
import sys
import json
import time
from typing import List, Dict, Any


class CLITester:
    def __init__(self, base_command: str = "uv run python -m apps.cli.agentarea_cli.main"):
        self.base_command = base_command
        self.test_results = []
        self.created_resources = {
            "llm_models": [],
            "agents": []
        }
    
    def run_command(self, command: str, expect_success: bool = True) -> Dict[str, Any]:
        """Run a CLI command and return the result."""
        full_command = f"{self.base_command} {command}"
        print(f"\n🔧 Running: {full_command}")
        
        try:
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            
            if expect_success and not success:
                print(f"❌ Command failed (exit code {result.returncode})")
                if output:
                    print(f"   Output: {output}")
                if error:
                    print(f"   Error: {error}")
            elif success:
                print(f"✅ Command succeeded")
                if output:
                    print(f"   Output: {output[:200]}{'...' if len(output) > 200 else ''}")
            
            return {
                "command": command,
                "success": success,
                "exit_code": result.returncode,
                "output": output,
                "error": error
            }
            
        except subprocess.TimeoutExpired:
            print(f"❌ Command timed out after 30 seconds")
            return {
                "command": command,
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": "Command timed out"
            }
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return {
                "command": command,
                "success": False,
                "exit_code": -1,
                "output": "",
                "error": str(e)
            }
    
    def test_llm_functionality(self):
        """Test LLM model management functionality."""
        print("\n" + "="*60)
        print("🧠 TESTING LLM FUNCTIONALITY")
        print("="*60)
        
        tests = [
            # List available LLM providers
            ("llm providers", True, "List LLM providers"),
            ("llm providers --format json", True, "List LLM providers (JSON)"),
            
            # List existing models
            ("llm list", True, "List LLM models"),
            ("llm list --format json", True, "List LLM models (JSON)"),
            
            # Create a test LLM model
            ('llm create --name "test-gpt-4" --provider "openai" --type "chat" --description "Test GPT-4 model for CLI testing"', True, "Create test LLM model"),
        ]
        
        for command, expect_success, description in tests:
            print(f"\n📋 {description}")
            result = self.run_command(command, expect_success)
            self.test_results.append((description, result["success"]))
            
            # Extract model ID if this was a create command
            if "llm create" in command and result["success"]:
                try:
                    # Try to extract model ID from output
                    output_lines = result["output"].split('\n')
                    for line in output_lines:
                        if "ID:" in line:
                            model_id = line.split("ID:")[1].strip()
                            self.created_resources["llm_models"].append(model_id)
                            print(f"   📝 Created model ID: {model_id}")
                            break
                except Exception as e:
                    print(f"   ⚠️  Could not extract model ID: {e}")
    
    def test_agent_with_llm(self):
        """Test creating agents with LLM models."""
        print("\n" + "="*60)
        print("🤖 TESTING AGENT WITH LLM FUNCTIONALITY")
        print("="*60)
        
        # First, get available models to use
        models_result = self.run_command("llm list --format json")
        if not models_result["success"]:
            print("❌ Cannot test agent creation - failed to get LLM models")
            return
        
        try:
            models_output = models_result["output"]
            if models_output:
                models = json.loads(models_output)
                if models and len(models) > 0:
                    model_id = models[0].get("id")
                    if model_id:
                        print(f"   📝 Using model ID: {model_id}")
                        
                        # Create an agent with the LLM model
                        create_command = f'agent create --name "test-designer" --description "A test designer agent for CLI testing" --instruction "You are a helpful designer agent that assists with creative tasks and design recommendations." --model-id "{model_id}"'
                        
                        print(f"\n📋 Creating agent with LLM model")
                        result = self.run_command(create_command)
                        self.test_results.append(("Create agent with LLM", result["success"]))
                        
                        # Extract agent ID
                        if result["success"]:
                            try:
                                output_lines = result["output"].split('\n')
                                for line in output_lines:
                                    if "ID:" in line:
                                        agent_id = line.split("ID:")[1].strip()
                                        self.created_resources["agents"].append(agent_id)
                                        print(f"   📝 Created agent ID: {agent_id}")
                                        break
                            except Exception as e:
                                print(f"   ⚠️  Could not extract agent ID: {e}")
                    else:
                        print("❌ No model ID found in first model")
                else:
                    print("❌ No models available for agent creation")
            else:
                print("❌ Empty models list output")
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse models JSON: {e}")
        except Exception as e:
            print(f"❌ Unexpected error getting models: {e}")
    
    def test_task_functionality(self):
        """Test task sending functionality."""
        print("\n" + "="*60)
        print("🚀 TESTING TASK FUNCTIONALITY")
        print("="*60)
        
        if not self.created_resources["agents"]:
            print("❌ No agents available for task testing")
            return
        
        agent_id = self.created_resources["agents"][0]
        
        # Test agent subcommand task
        task_tests = [
            (f'agent task "{agent_id}" "Design a simple logo for a coffee shop"', True, "Send task via agent subcommand"),
            (f'agent task "{agent_id}" "What are some good color schemes for a modern website?" --format json', True, "Send task via agent subcommand (JSON)"),
        ]
        
        for command, expect_success, description in task_tests:
            print(f"\n📋 {description}")
            result = self.run_command(command, expect_success)
            self.test_results.append((description, result["success"]))
        
        # Test global --agent option task
        global_task_tests = [
            (f'--agent "{agent_id}" task "Find some good design inspiration for a mobile app"', True, "Send task via global --agent option (ID)"),
            (f'--agent "test-designer" task "What are the latest design trends?"', True, "Send task via global --agent option (name)"),
        ]
        
        for command, expect_success, description in global_task_tests:
            print(f"\n📋 {description}")
            result = self.run_command(command, expect_success)
            self.test_results.append((description, result["success"]))
    
    def cleanup_resources(self):
        """Clean up created test resources."""
        print("\n" + "="*60)
        print("🧹 CLEANING UP TEST RESOURCES")
        print("="*60)
        
        # Delete created agents
        for agent_id in self.created_resources["agents"]:
            print(f"\n📋 Deleting agent: {agent_id}")
            result = self.run_command(f"agent delete {agent_id} --force")
            self.test_results.append((f"Delete agent {agent_id}", result["success"]))
        
        # Delete created LLM models
        for model_id in self.created_resources["llm_models"]:
            print(f"\n📋 Deleting LLM model: {model_id}")
            result = self.run_command(f"llm delete {model_id} --force")
            self.test_results.append((f"Delete LLM model {model_id}", result["success"]))
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for _, success in self.test_results if success)
        total = len(self.test_results)
        
        print(f"\n✅ Passed: {passed}/{total} tests")
        
        if passed < total:
            print("\n❌ Failed tests:")
            for description, success in self.test_results:
                if not success:
                    print(f"   - {description}")
        
        print("\n📋 Test breakdown:")
        for description, success in self.test_results:
            status = "✅" if success else "❌"
            print(f"   {status} {description}")
        
        return passed, total


def main():
    """Main test execution."""
    print("🧪 AgentArea CLI - LLM Configuration and Task Functionality Test")
    print("=" * 70)
    
    tester = CLITester()
    
    try:
        # Test authentication status first
        print("\n📋 Checking authentication status")
        auth_result = tester.run_command("auth status")
        if not auth_result["success"]:
            print("❌ Authentication check failed. Please ensure you're logged in.")
            print("   Run: agentarea auth login")
            return 1
        
        # Run all tests
        tester.test_llm_functionality()
        tester.test_agent_with_llm()
        tester.test_task_functionality()
        
        # Clean up
        tester.cleanup_resources()
        
        # Print summary
        passed, total = tester.print_summary()
        
        if passed == total:
            print("\n🎉 All tests passed! LLM configuration and task functionality is working correctly.")
            return 0
        else:
            print(f"\n⚠️  {total - passed} tests failed. Please check the output above for details.")
            return 1
            
    except KeyboardInterrupt:
        print("\n❌ Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error during testing: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())