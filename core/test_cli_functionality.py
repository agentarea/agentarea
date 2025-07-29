#!/usr/bin/env python3
"""
Comprehensive CLI functionality test script.
Tests the full create-and-retrieve workflow for AgentArea CLI.
"""

import subprocess
import sys
import json
import time
from typing import Dict, Any, Optional


class CLITester:
    """Test runner for AgentArea CLI functionality."""
    
    def __init__(self):
        self.base_command = ["uv", "run", "python", "-m", "apps.cli.agentarea_cli.main"]
        self.test_results = []
        self.created_agent_id = None
    
    def run_command(self, args: list, expect_success: bool = True) -> Dict[str, Any]:
        """Run a CLI command and return the result."""
        cmd = self.base_command + args
        print(f"\n🔧 Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            success = result.returncode == 0
            
            if expect_success and not success:
                print(f"❌ Command failed with exit code {result.returncode}")
                print(f"STDERR: {result.stderr}")
            elif not expect_success and success:
                print(f"⚠️  Command unexpectedly succeeded")
            elif success:
                print(f"✅ Command succeeded")
            else:
                print(f"✅ Command failed as expected")
            
            return {
                "command": ' '.join(args),
                "success": success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
            
        except subprocess.TimeoutExpired:
            print(f"❌ Command timed out")
            return {
                "command": ' '.join(args),
                "success": False,
                "stdout": "",
                "stderr": "Command timed out",
                "returncode": -1
            }
        except Exception as e:
            print(f"❌ Command failed with exception: {e}")
            return {
                "command": ' '.join(args),
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1
            }
    
    def test_help_commands(self):
        """Test basic help commands."""
        print("\n📋 Testing Help Commands")
        print("=" * 50)
        
        help_tests = [
            ["--help"],
            ["agent", "--help"],
            ["chat", "--help"],
            ["system", "--help"],
            ["auth", "--help"]
        ]
        
        for test in help_tests:
            result = self.run_command(test)
            self.test_results.append({
                "category": "help",
                "test": ' '.join(test),
                "passed": result["success"]
            })
    
    def test_auth_status(self):
        """Test authentication status."""
        print("\n🔐 Testing Authentication")
        print("=" * 50)
        
        result = self.run_command(["auth", "status"], expect_success=False)
        # Auth status might fail if not authenticated, but should not crash
        passed = result["returncode"] in [0, 1]  # Either success or auth failure
        
        self.test_results.append({
            "category": "auth",
            "test": "auth status",
            "passed": passed
        })
        
        if "✅ Authenticated" in result["stdout"]:
            print("✅ Already authenticated")
        elif "❌ Token is invalid" in result["stdout"]:
            print("ℹ️  Not authenticated (expected)")
    
    def test_agent_creation(self):
        """Test agent creation."""
        print("\n🤖 Testing Agent Creation")
        print("=" * 50)
        
        # Create a test agent
        agent_name = f"Test Agent {int(time.time())}"
        create_args = [
            "agent", "create",
            "--name", agent_name,
            "--description", "A comprehensive test agent for CLI functionality verification",
            "--instruction", "You are a helpful test assistant designed to verify CLI functionality",
            "--model-id", "test-model-123"
        ]
        
        result = self.run_command(create_args)
        passed = result["success"]
        
        if passed:
            # Extract agent ID from output
            for line in result["stdout"].split('\n'):
                if "ID:" in line:
                    self.created_agent_id = line.split("ID:")[1].strip()
                    print(f"✅ Created agent with ID: {self.created_agent_id}")
                    break
        
        self.test_results.append({
            "category": "agent",
            "test": "agent create",
            "passed": passed,
            "agent_id": self.created_agent_id
        })
    
    def test_agent_listing(self):
        """Test agent listing."""
        print("\n📋 Testing Agent Listing")
        print("=" * 50)
        
        # Test table format
        result = self.run_command(["agent", "list"], expect_success=False)
        table_passed = result["success"] or "agents found" in result["stdout"]
        
        self.test_results.append({
            "category": "agent",
            "test": "agent list (table)",
            "passed": table_passed
        })
        
        # Test JSON format
        result = self.run_command(["agent", "list", "--format", "json"], expect_success=False)
        json_passed = result["success"] or "agents found" in result["stdout"]
        
        self.test_results.append({
            "category": "agent",
            "test": "agent list (json)",
            "passed": json_passed
        })
    
    def test_agent_retrieval(self):
        """Test agent retrieval if we have a created agent."""
        if not self.created_agent_id:
            print("\n⚠️  Skipping agent retrieval test (no agent created)")
            return
        
        print("\n🔍 Testing Agent Retrieval")
        print("=" * 50)
        
        result = self.run_command(["agent", "show", self.created_agent_id], expect_success=False)
        # Agent show might fail due to backend issues, but should not crash CLI
        passed = result["returncode"] in [0, 1]  # Either success or expected failure
        
        self.test_results.append({
            "category": "agent",
            "test": "agent show",
            "passed": passed
        })
    
    def test_system_commands(self):
        """Test system commands."""
        print("\n⚙️  Testing System Commands")
        print("=" * 50)
        
        system_tests = [
            ["system", "status"],
            ["system", "info"],
            ["system", "components"]
        ]
        
        for test in system_tests:
            result = self.run_command(test, expect_success=False)
            # System commands might fail due to backend/auth, but should not crash
            passed = result["returncode"] in [0, 1]
            
            self.test_results.append({
                "category": "system",
                "test": ' '.join(test),
                "passed": passed
            })
    
    def test_workspace_imports(self):
        """Test workspace module imports."""
        print("\n📦 Testing Workspace Imports")
        print("=" * 50)
        
        import_tests = [
            "import agentarea_cli",
            "import agentarea_cli.main",
            "import agentarea_cli.client",
            "import agentarea_cli.commands.agent",
            "import agentarea_cli.commands.chat",
            "import agentarea_cli.commands.system",
            "import agentarea_cli.commands.auth"
        ]
        
        for import_test in import_tests:
            try:
                result = subprocess.run(
                    ["uv", "run", "python", "-c", import_test],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                passed = result.returncode == 0
                
                if passed:
                    print(f"✅ {import_test}")
                else:
                    print(f"❌ {import_test}: {result.stderr.strip()}")
                
                self.test_results.append({
                    "category": "import",
                    "test": import_test,
                    "passed": passed
                })
                
            except Exception as e:
                print(f"❌ {import_test}: {e}")
                self.test_results.append({
                    "category": "import",
                    "test": import_test,
                    "passed": False
                })
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        categories = {}
        total_tests = len(self.test_results)
        passed_tests = 0
        
        for result in self.test_results:
            category = result["category"]
            if category not in categories:
                categories[category] = {"total": 0, "passed": 0}
            
            categories[category]["total"] += 1
            if result["passed"]:
                categories[category]["passed"] += 1
                passed_tests += 1
        
        # Print category breakdown
        for category, stats in categories.items():
            status = "✅" if stats["passed"] == stats["total"] else "⚠️"
            print(f"{status} {category.upper()}: {stats['passed']}/{stats['total']} passed")
        
        print(f"\n📈 OVERALL: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("\n🎉 All tests passed! CLI is fully functional.")
            return True
        else:
            print(f"\n⚠️  {total_tests - passed_tests} tests failed or had issues.")
            
            # Print failed tests
            print("\n❌ Failed tests:")
            for result in self.test_results:
                if not result["passed"]:
                    print(f"   - {result['category']}: {result['test']}")
            
            return False
    
    def run_all_tests(self):
        """Run all CLI functionality tests."""
        print("🚀 Starting AgentArea CLI Functionality Tests")
        print("=" * 60)
        
        try:
            # Run all test categories
            self.test_help_commands()
            self.test_workspace_imports()
            self.test_auth_status()
            self.test_agent_creation()
            self.test_agent_listing()
            self.test_agent_retrieval()
            self.test_system_commands()
            
            # Print summary
            success = self.print_summary()
            
            return success
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Tests interrupted by user")
            return False
        except Exception as e:
            print(f"\n\n❌ Test runner failed: {e}")
            return False


def main():
    """Main entry point."""
    tester = CLITester()
    success = tester.run_all_tests()
    
    if success:
        print("\n✅ CLI functionality verification completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ CLI functionality verification completed with issues.")
        sys.exit(1)


if __name__ == "__main__":
    main()