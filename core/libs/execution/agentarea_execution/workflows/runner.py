"""Agent execution runner for orchestrating the main execution loop."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio import workflow

logger = logging.getLogger(__name__)


class AgentExecutionRunner:
    """Handles the main execution loop logic for agent workflows.
    
    This class extracts the complex while True loop from the workflow
    to make it more testable and maintainable.
    """

    def __init__(
        self,
        should_continue_check: Callable[[], tuple[bool, str]],
        execute_iteration: Callable[[], Awaitable[None]],
        pause_check: Callable[[], bool],
        wait_for_unpause: Callable[[], Awaitable[None]],
    ):
        """Initialize the runner with required callbacks.
        
        Args:
            should_continue_check: Function that returns (should_continue, reason)
            execute_iteration: Async function that executes one iteration
            pause_check: Function that returns True if execution is paused
            wait_for_unpause: Async function that waits for unpause
        """
        self.should_continue_check = should_continue_check
        self.execute_iteration = execute_iteration
        self.pause_check = pause_check
        self.wait_for_unpause = wait_for_unpause
        self.current_iteration = 0

    async def run(self) -> dict[str, Any]:
        """Execute the main agent loop.
        
        Returns:
            Dict containing execution results
        """
        workflow.logger.info("Starting agent execution runner")

        while True:
            # Increment iteration count
            self.current_iteration += 1

            # Check if we should continue before starting the iteration
            should_continue, reason = self.should_continue_check()
            if not should_continue:
                workflow.logger.info(f"Stopping execution before iteration {self.current_iteration}: {reason}")
                # Decrement since we didn't actually execute this iteration
                self.current_iteration -= 1
                break

            workflow.logger.info(f"Starting iteration {self.current_iteration}")

            # Execute iteration
            await self.execute_iteration()

            # Check if we should finish after completing the iteration
            should_continue, reason = self.should_continue_check()
            if not should_continue:
                workflow.logger.info(f"Stopping execution after iteration {self.current_iteration}: {reason}")
                break

            # Check for pause
            if self.pause_check():
                workflow.logger.info(f"Execution paused at iteration {self.current_iteration}")
                await self.wait_for_unpause()
                workflow.logger.info(f"Execution resumed at iteration {self.current_iteration}")

        workflow.logger.info(f"Agent execution completed after {self.current_iteration} iterations")
        return {"iterations_completed": self.current_iteration}


class ExecutionTerminator:
    """Handles termination conditions for agent execution."""

    def __init__(self, state, budget_tracker, max_iterations: int = 25):
        """Initialize terminator with state and budget tracker.
        
        Args:
            state: Workflow state object
            budget_tracker: Budget tracking object
            max_iterations: Maximum iterations allowed
        """
        self.state = state
        self.budget_tracker = budget_tracker
        self.max_iterations = max_iterations

    def should_continue(self) -> tuple[bool, str]:
        """Check if execution should continue.
        
        Returns:
            tuple[bool, str]: (should_continue, reason_for_stopping)
        """
        # Check if goal is achieved (highest priority)
        if hasattr(self.state, 'success') and self.state.success:
            return False, "Goal achieved successfully"

        # Check maximum iterations
        current_iteration = getattr(self.state, 'current_iteration', 0)
        if current_iteration >= self.max_iterations:
            return False, f"Maximum iterations reached ({self.max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            return False, f"Budget exceeded (${self.budget_tracker.cost:.2f}/${self.budget_tracker.budget_limit:.2f})"

        # If we get here, execution should continue
        return True, "Continue execution"


class IterationExecutor:
    """Handles execution of individual iterations."""

    def __init__(self, workflow_instance, activities, event_manager):
        """Initialize iteration executor.
        
        Args:
            workflow_instance: The workflow instance
            activities: Activities interface
            event_manager: Event manager for tracking
        """
        self.workflow = workflow_instance
        self.activities = activities
        self.event_manager = event_manager

    async def execute(self) -> None:
        """Execute a single iteration."""
        iteration = self.workflow.state.current_iteration

        # Log iteration start
        self.event_manager.add_event("iteration_started", {
            "iteration": iteration,
            "budget_remaining": self.workflow.budget_tracker.get_remaining() if self.workflow.budget_tracker else 0
        })

        try:
            # Execute the iteration logic
            await self._execute_iteration_logic()

            # Check budget warnings
            await self._check_budget_status()

            # Log iteration completion
            self.event_manager.add_event("iteration_completed", {
                "iteration": iteration,
                "success": True
            })

        except Exception as e:
            # Log iteration failure
            self.event_manager.add_event("iteration_failed", {
                "iteration": iteration,
                "error": str(e)
            })
            raise

    async def _execute_iteration_logic(self) -> None:
        """Execute the core iteration logic."""
        # This would contain the actual iteration execution
        # For now, this is a placeholder that would be implemented
        # based on the specific workflow needs
        pass

    async def _check_budget_status(self) -> None:
        """Check and handle budget status."""
        if self.workflow.budget_tracker and self.workflow.budget_tracker.should_warn():
            self.workflow.budget_tracker.mark_warning_sent()
            self.event_manager.add_event("budget_warning", {
                "usage_percentage": self.workflow.budget_tracker.get_usage_percentage(),
                "cost": self.workflow.budget_tracker.cost,
                "limit": self.workflow.budget_tracker.budget_limit
            })
