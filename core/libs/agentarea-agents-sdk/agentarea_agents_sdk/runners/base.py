"""Base classes and interfaces for agent execution runners."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Structured message for conversation history."""

    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class AgentGoal:
    """Agent goal definition."""

    description: str
    success_criteria: list[str]
    max_iterations: int = 10
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunnerConfig:
    """Configuration for agent runners."""

    max_iterations: int = 25
    budget_limit: float | None = None
    temperature: float = 0.1
    enable_pause: bool = False


@dataclass
class ExecutionResult:
    """Result from agent execution."""

    success: bool
    current_iteration: int
    messages: list[Message] = field(default_factory=list)
    final_response: str | None = None
    total_cost: float = 0.0
    termination_reason: str = ""


class ExecutionTerminator:
    """Handles termination conditions for agent execution."""

    def __init__(self, config: RunnerConfig):
        """Initialize terminator with configuration.

        Args:
            config: Runner configuration
        """
        self.config = config
        self.budget_tracker = None  # Will be set by runner

    def should_continue(self, state: Any) -> tuple[bool, str]:
        """Check if execution should continue.

        Args:
            state: Current execution state

        Returns:
            tuple[bool, str]: (should_continue, reason_for_stopping)
        """
        # Check if goal is achieved (highest priority)
        if hasattr(state, "success") and state.success:
            return False, "Goal achieved successfully"

        # Check maximum iterations - use goal's max_iterations if available
        current_iteration = getattr(state, "current_iteration", 0)
        max_iterations = self.config.max_iterations
        if hasattr(state, "goal") and state.goal and hasattr(state.goal, "max_iterations"):
            max_iterations = state.goal.max_iterations

        if current_iteration >= max_iterations:
            return False, f"Maximum iterations reached ({max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            return (
                False,
                f"Budget exceeded (${self.budget_tracker.cost:.2f}/${self.budget_tracker.budget_limit:.2f})",
            )

        # If we get here, execution should continue
        return True, "Continue execution"


class BaseAgentRunner(ABC):
    """Base class for agent execution runners.

    Provides a unified interface for different execution environments
    (synchronous, Temporal workflow, etc.) while maintaining consistent
    behavior and termination conditions.
    """

    def __init__(self, config: RunnerConfig | None = None):
        """Initialize the base runner.

        Args:
            config: Runner configuration
        """
        self.config = config or RunnerConfig()
        self.terminator = ExecutionTerminator(self.config)
        self.current_iteration = 0

    @abstractmethod
    async def run(self, goal: AgentGoal) -> ExecutionResult:
        """Execute the agent workflow.

        Args:
            goal: The goal to achieve

        Returns:
            ExecutionResult with final results
        """
        pass

    @abstractmethod
    async def _execute_iteration(self, state: Any) -> None:
        """Execute a single iteration.

        Args:
            state: Current execution state
        """
        pass

    def _should_continue(self, state: Any) -> tuple[bool, str]:
        """Check if execution should continue.

        Args:
            state: Current execution state

        Returns:
            tuple[bool, str]: (should_continue, reason_for_stopping)
        """
        return self.terminator.should_continue(state)

    async def _execute_main_loop(
        self,
        state: Any,
        pause_check: Callable[[], bool] | None = None,
        wait_for_unpause: Callable[[], Any] | None = None,
    ) -> ExecutionResult:
        """Execute the main agent loop with unified termination logic.

        Args:
            state: Execution state object
            pause_check: Optional function to check if execution is paused
            wait_for_unpause: Optional function to wait for unpause

        Returns:
            ExecutionResult with final results
        """
        logger.info("Starting agent execution main loop")

        while True:
            # Increment iteration count
            state.current_iteration += 1
            self.current_iteration = state.current_iteration

            logger.info(f"Starting iteration {state.current_iteration}")

            # Execute iteration
            await self._execute_iteration(state)

            # Check if we should finish after completing the iteration
            should_continue, reason = self._should_continue(state)
            if not should_continue:
                logger.info(
                    f"Stopping execution after iteration {state.current_iteration}: {reason}"
                )
                break

            # Check for pause (if supported)
            if pause_check and pause_check():
                logger.info(f"Execution paused at iteration {state.current_iteration}")
                if wait_for_unpause:
                    await wait_for_unpause()
                logger.info(f"Execution resumed at iteration {state.current_iteration}")

        logger.info(f"Agent execution completed after {state.current_iteration} iterations")

        return ExecutionResult(
            success=getattr(state, "success", False),
            current_iteration=state.current_iteration,
            messages=getattr(state, "messages", []),
            final_response=getattr(state, "final_response", None),
            total_cost=getattr(state, "total_cost", 0.0),
            termination_reason=reason,
        )
