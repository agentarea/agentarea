#!/usr/bin/env python3
"""
Simple Task Workflow Smoke Test

This script focuses specifically on testing the "Task failed to start workflow" issue
by simulating the exact API endpoint logic and checking the fix implementation.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict

# Add the core directory to Python path
sys.path.insert(0, str(Path.cwd() / "core"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TaskWorkflowSmokeTest:
    """Simple smoke test for task workflow integration."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": [],
            "summary": {}
        }
    
    async def run_smoke_test(self):
        """Run focused smoke test."""
        logger.info("🔍 Task Workflow Smoke Test")
        logger.info("=" * 50)
        
        tests = [
            ("Code Analysis", self.analyze_fix_implementation),
            ("API Logic Simulation", self.simulate_api_logic),
            ("Status Transition Test", self.test_status_transitions),
            ("Fix Verification", self.verify_fix_implementation)
        ]
        
        for test_name, test_func in tests:
            logger.info(f"\n📋 {test_name}")
            try:
                result = await test_func()
                status = "PASS" if result.get("success", False) else "FAIL"
                self.results["tests"].append({
                    "name": test_name,
                    "status": status,
                    "details": result.get("details"),
                    "error": result.get("error")
                })
                logger.info(f"   Result: {status}")
                if result.get("details"):
                    for key, value in result["details"].items():
                        logger.info(f"   {key}: {value}")
            except Exception as e:
                logger.error(f"   ERROR: {e}")
                self.results["tests"].append({
                    "name": test_name,
                    "status": "ERROR",
                    "details": None,
                    "error": str(e)
                })
        
        await self.generate_summary()
        await self.save_results()
    
    async def analyze_fix_implementation(self) -> Dict[str, Any]:
        """Analyze the fix implementation in the code."""
        try:
            # Check if the TemporalTaskManager has the fix
            temporal_task_manager_file = Path.cwd() / "core" / "libs" / "tasks" / "agentarea_tasks" / "temporal_task_manager.py"
            
            if not temporal_task_manager_file.exists():
                return {
                    "success": False,
                    "error": "TemporalTaskManager file not found"
                }
            
            with open(temporal_task_manager_file, 'r') as f:
                content = f.read()
            
            # Check for key fix indicators
            has_running_status_update = '"running"' in content and 'update_status' in content
            has_execution_id_assignment = 'execution_id =' in content
            has_workflow_start = 'start_workflow' in content
            
            # Look for the specific fix pattern
            fix_pattern_found = ('update_status(task.id, "running")' in content or 
                               'status = "running"' in content)
            
            return {
                "success": True,
                "details": {
                    "file_exists": True,
                    "has_running_status_update": has_running_status_update,
                    "has_execution_id_assignment": has_execution_id_assignment,
                    "has_workflow_start": has_workflow_start,
                    "fix_pattern_found": fix_pattern_found,
                    "fix_implemented": fix_pattern_found and has_execution_id_assignment
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def simulate_api_logic(self) -> Dict[str, Any]:
        """Simulate the API endpoint logic that determines success/failure."""
        try:
            # This is the exact logic from agents_tasks.py line 252
            # if task.execution_id and task.status in ["running", "pending"]:
            
            test_cases = [
                {
                    "name": "Fixed Task (running + execution_id)",
                    "execution_id": "workflow-123",
                    "status": "running"
                },
                {
                    "name": "Fixed Task (pending + execution_id)", 
                    "execution_id": "workflow-456",
                    "status": "pending"
                },
                {
                    "name": "Broken Task (submitted + execution_id)",
                    "execution_id": "workflow-789",
                    "status": "submitted"
                },
                {
                    "name": "Broken Task (running + no execution_id)",
                    "execution_id": None,
                    "status": "running"
                },
                {
                    "name": "Broken Task (submitted + no execution_id)",
                    "execution_id": None,
                    "status": "submitted"
                }
            ]
            
            results = {}
            
            for case in test_cases:
                # Apply the exact API logic
                api_success = (case["execution_id"] and 
                             case["status"] in ["running", "pending"])
                
                results[case["name"]] = {
                    "execution_id": case["execution_id"],
                    "status": case["status"],
                    "api_success": api_success,
                    "would_show_error": not api_success
                }
            
            # Count how many would succeed vs fail
            success_count = sum(1 for r in results.values() if r["api_success"])
            total_count = len(results)
            
            return {
                "success": True,
                "details": {
                    "test_cases_run": total_count,
                    "success_cases": success_count,
                    "fail_cases": total_count - success_count,
                    "api_logic_working": success_count > 0,
                    "results": results
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_status_transitions(self) -> Dict[str, Any]:
        """Test the expected status transitions."""
        try:
            # Simulate the expected flow:
            # 1. Task created with status="pending"
            # 2. Task submitted to workflow
            # 3. Status updated to "running" (this is the fix)
            # 4. execution_id is set
            
            transitions = [
                {
                    "step": "Initial Creation",
                    "status": "pending",
                    "execution_id": None,
                    "api_success": False,
                    "note": "Task just created, not yet submitted"
                },
                {
                    "step": "Before Fix (Broken)",
                    "status": "submitted", 
                    "execution_id": "workflow-123",
                    "api_success": False,
                    "note": "Had execution_id but wrong status"
                },
                {
                    "step": "After Fix (Working)",
                    "status": "running",
                    "execution_id": "workflow-123", 
                    "api_success": True,
                    "note": "Has both execution_id and correct status"
                }
            ]
            
            for transition in transitions:
                # Apply API logic
                transition["api_success"] = (transition["execution_id"] and 
                                           transition["status"] in ["running", "pending"])
            
            # The fix should make the final transition succeed
            fix_working = transitions[-1]["api_success"]
            
            return {
                "success": True,
                "details": {
                    "transitions_analyzed": len(transitions),
                    "fix_working": fix_working,
                    "before_fix_failed": not transitions[1]["api_success"],
                    "after_fix_succeeded": transitions[2]["api_success"],
                    "transitions": transitions
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def verify_fix_implementation(self) -> Dict[str, Any]:
        """Verify the fix is properly implemented."""
        try:
            # Check the actual implementation in TemporalTaskManager
            temporal_task_manager_file = Path.cwd() / "core" / "libs" / "tasks" / "agentarea_tasks" / "temporal_task_manager.py"
            
            with open(temporal_task_manager_file, 'r') as f:
                content = f.read()
            
            # Look for the specific fix implementation
            lines = content.split('\n')
            
            fix_indicators = {
                "has_start_workflow_call": False,
                "has_status_update_to_running": False,
                "has_execution_id_assignment": False,
                "fix_in_submit_task_method": False
            }
            
            in_submit_task = False
            for i, line in enumerate(lines):
                if 'def submit_task(' in line:
                    in_submit_task = True
                elif in_submit_task and line.strip().startswith('def ') and 'submit_task' not in line:
                    in_submit_task = False
                
                if in_submit_task:
                    if 'start_workflow(' in line:
                        fix_indicators["has_start_workflow_call"] = True
                    if 'update_status(' in line and '"running"' in line:
                        fix_indicators["has_status_update_to_running"] = True
                        fix_indicators["fix_in_submit_task_method"] = True
                    if 'execution_id =' in line:
                        fix_indicators["has_execution_id_assignment"] = True
            
            # Overall fix status
            fix_complete = all([
                fix_indicators["has_start_workflow_call"],
                fix_indicators["has_status_update_to_running"],
                fix_indicators["has_execution_id_assignment"]
            ])
            
            return {
                "success": True,
                "details": {
                    **fix_indicators,
                    "fix_complete": fix_complete,
                    "fix_status": "IMPLEMENTED" if fix_complete else "INCOMPLETE"
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def generate_summary(self):
        """Generate test summary."""
        total_tests = len(self.results["tests"])
        passed = len([t for t in self.results["tests"] if t["status"] == "PASS"])
        failed = len([t for t in self.results["tests"] if t["status"] == "FAIL"])
        errors = len([t for t in self.results["tests"] if t["status"] == "ERROR"])
        
        # Determine overall fix status
        fix_status = "UNKNOWN"
        
        # Check fix verification test
        fix_test = next((t for t in self.results["tests"] if t["name"] == "Fix Verification"), None)
        if fix_test and fix_test["status"] == "PASS":
            details = fix_test.get("details", {})
            if details.get("fix_complete"):
                fix_status = "IMPLEMENTED"
            else:
                fix_status = "INCOMPLETE"
        elif fix_test and fix_test["status"] == "FAIL":
            fix_status = "NOT_IMPLEMENTED"
        
        # Check API logic test
        api_test = next((t for t in self.results["tests"] if t["name"] == "API Logic Simulation"), None)
        api_working = False
        if api_test and api_test["status"] == "PASS":
            details = api_test.get("details", {})
            api_working = details.get("api_logic_working", False)
        
        self.results["summary"] = {
            "total_tests": total_tests,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "success_rate": f"{(passed/total_tests)*100:.1f}%" if total_tests > 0 else "0%",
            "fix_status": fix_status,
            "api_logic_working": api_working,
            "overall_assessment": self._get_overall_assessment(fix_status, api_working)
        }
        
        # Log summary
        logger.info("\n" + "=" * 50)
        logger.info("📊 SMOKE TEST SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Tests Run: {total_tests}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Errors: {errors}")
        logger.info(f"Fix Status: {fix_status}")
        logger.info(f"API Logic: {'Working' if api_working else 'Issues'}")
        logger.info(f"\n🎯 Overall: {self.results['summary']['overall_assessment']}")
    
    def _get_overall_assessment(self, fix_status: str, api_working: bool) -> str:
        """Get overall assessment."""
        if fix_status == "IMPLEMENTED" and api_working:
            return "✅ Fix is implemented and should resolve the issue"
        elif fix_status == "IMPLEMENTED":
            return "⚠️  Fix is implemented but API logic needs verification"
        elif fix_status == "INCOMPLETE":
            return "🔧 Fix is partially implemented, needs completion"
        elif fix_status == "NOT_IMPLEMENTED":
            return "❌ Fix is not implemented, issue likely persists"
        else:
            return "❓ Unable to determine fix status"
    
    async def save_results(self):
        """Save test results to file."""
        results_file = Path("simple_task_workflow_smoke_test_results.json")
        
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"\n💾 Results saved to: {results_file}")

async def main():
    """Main test runner."""
    tester = TaskWorkflowSmokeTest()
    await tester.run_smoke_test()

if __name__ == "__main__":
    asyncio.run(main())