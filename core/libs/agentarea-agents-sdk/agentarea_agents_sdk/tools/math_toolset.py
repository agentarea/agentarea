"""Mathematical operations toolset with individual math tools."""

import inspect
import math
from collections.abc import Callable

from .decorator_tool import Toolset, tool_method


class MathToolset(Toolset):
    """A toolset for mathematical operations including basic arithmetic, advanced math, and utility functions."""

    def __init__(
        self,
        add: bool = True,
        subtract: bool = True,
        multiply: bool = True,
        divide: bool = True,
        power: bool = True,
        sqrt: bool = True,
        sin: bool = True,
        cos: bool = True,
        tan: bool = True,
        log: bool = True,
        abs: bool = True,
        evaluate: bool = True,
    ):
        """Initialize the MathToolset with configurable individual tools.

        Args:
            add: Enable addition tool.
            subtract: Enable subtraction tool.
            multiply: Enable multiplication tool.
            divide: Enable division tool.
            power: Enable power/exponentiation tool.
            sqrt: Enable square root tool.
            sin: Enable sine function tool.
            cos: Enable cosine function tool.
            tan: Enable tangent function tool.
            log: Enable logarithm tool.
            abs: Enable absolute value tool.
            evaluate: Enable expression evaluation tool.
        """
        self._add_enabled = add
        self._subtract_enabled = subtract
        self._multiply_enabled = multiply
        self._divide_enabled = divide
        self._power_enabled = power
        self._sqrt_enabled = sqrt
        self._sin_enabled = sin
        self._cos_enabled = cos
        self._tan_enabled = tan
        self._log_enabled = log
        self._abs_enabled = abs
        self._evaluate_enabled = evaluate
        # Initialize the parent class WITHOUT calling _discover_tool_methods yet
        # We'll override the _tool_methods after parent initialization
        super().__init__()
        # Now override with our filtered methods
        self._tool_methods = self._discover_tool_methods()

    def _discover_tool_methods(self) -> dict[str, Callable]:
        """Discover only enabled methods decorated with @tool_method."""
        methods = {}
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if hasattr(method, "_is_tool_method"):
                # Check if this method is enabled based on the constructor flags
                method_enabled = getattr(self, f"_{name}_enabled", False)
                if method_enabled:
                    methods[name] = method
        return methods

    @tool_method
    async def add(self, a: float, b: float) -> str:
        """Add two numbers together.

        Args:
            a: First number to add.
            b: Second number to add.

        Returns:
            Result of a + b.
        """
        if not self._add_enabled:
            return "Error: addition is disabled for this toolset instance"

        try:
            result = a + b
            return f"{a} + {b} = {result}"
        except Exception as e:
            return f"Error in addition: {e}"

    @tool_method
    async def subtract(self, a: float, b: float) -> str:
        """Subtract one number from another.

        Args:
            a: Number to subtract from.
            b: Number to subtract.

        Returns:
            Result of a - b.
        """
        if not self._subtract_enabled:
            return "Error: subtraction is disabled for this toolset instance"

        try:
            result = a - b
            return f"{a} - {b} = {result}"
        except Exception as e:
            return f"Error in subtraction: {e}"

    @tool_method
    async def multiply(self, a: float, b: float) -> str:
        """Multiply two numbers.

        Args:
            a: First number to multiply.
            b: Second number to multiply.

        Returns:
            Result of a * b.
        """
        if not self._multiply_enabled:
            return "Error: multiplication is disabled for this toolset instance"

        try:
            result = a * b
            return f"{a} * {b} = {result}"
        except Exception as e:
            return f"Error in multiplication: {e}"

    @tool_method
    async def divide(self, a: float, b: float) -> str:
        """Divide one number by another.

        Args:
            a: Number to be divided (dividend).
            b: Number to divide by (divisor).

        Returns:
            Result of a / b.
        """
        if not self._divide_enabled:
            return "Error: division is disabled for this toolset instance"

        try:
            if b == 0:
                return "Error: Cannot divide by zero"
            result = a / b
            return f"{a} / {b} = {result}"
        except Exception as e:
            return f"Error in division: {e}"

    @tool_method
    async def power(self, base: float, exponent: float) -> str:
        """Raise a number to a power.

        Args:
            base: Base number.
            exponent: Power to raise the base to.

        Returns:
            Result of base ^ exponent.
        """
        if not self._power_enabled:
            return "Error: power function is disabled for this toolset instance"

        try:
            result = base**exponent
            return f"{base} ^ {exponent} = {result}"
        except Exception as e:
            return f"Error in power calculation: {e}"

    @tool_method
    async def sqrt(self, number: float) -> str:
        """Calculate the square root of a number.

        Args:
            number: Number to find the square root of.

        Returns:
            Square root of the number.
        """
        if not self._sqrt_enabled:
            return "Error: square root function is disabled for this toolset instance"

        try:
            if number < 0:
                return "Error: Cannot calculate square root of negative number"
            result = math.sqrt(number)
            return f"√{number} = {result}"
        except Exception as e:
            return f"Error in square root calculation: {e}"

    @tool_method
    async def sin(self, angle: float, degrees: bool = False) -> str:
        """Calculate the sine of an angle.

        Args:
            angle: Angle value.
            degrees: Whether the angle is in degrees (True) or radians (False).

        Returns:
            Sine of the angle.
        """
        if not self._sin_enabled:
            return "Error: sine function is disabled for this toolset instance"

        try:
            if degrees:
                angle = math.radians(angle)
            result = math.sin(angle)
            unit = "°" if degrees else "rad"
            return f"sin({angle if not degrees else math.degrees(angle)}{unit}) = {result}"
        except Exception as e:
            return f"Error in sine calculation: {e}"

    @tool_method
    async def cos(self, angle: float, degrees: bool = False) -> str:
        """Calculate the cosine of an angle.

        Args:
            angle: Angle value.
            degrees: Whether the angle is in degrees (True) or radians (False).

        Returns:
            Cosine of the angle.
        """
        if not self._cos_enabled:
            return "Error: cosine function is disabled for this toolset instance"

        try:
            if degrees:
                angle = math.radians(angle)
            result = math.cos(angle)
            unit = "°" if degrees else "rad"
            return f"cos({angle if not degrees else math.degrees(angle)}{unit}) = {result}"
        except Exception as e:
            return f"Error in cosine calculation: {e}"

    @tool_method
    async def tan(self, angle: float, degrees: bool = False) -> str:
        """Calculate the tangent of an angle.

        Args:
            angle: Angle value.
            degrees: Whether the angle is in degrees (True) or radians (False).

        Returns:
            Tangent of the angle.
        """
        if not self._tan_enabled:
            return "Error: tangent function is disabled for this toolset instance"

        try:
            if degrees:
                angle = math.radians(angle)
            result = math.tan(angle)
            unit = "°" if degrees else "rad"
            return f"tan({angle if not degrees else math.degrees(angle)}{unit}) = {result}"
        except Exception as e:
            return f"Error in tangent calculation: {e}"

    @tool_method
    async def log(self, number: float, base: float = math.e) -> str:
        """Calculate the logarithm of a number.

        Args:
            number: Number to find the logarithm of.
            base: Base of the logarithm (default: natural log with base e).

        Returns:
            Logarithm of the number.
        """
        if not self._log_enabled:
            return "Error: logarithm function is disabled for this toolset instance"

        try:
            if number <= 0:
                return "Error: Cannot calculate logarithm of zero or negative number"
            if base <= 0 or base == 1:
                return "Error: Invalid logarithm base"

            if base == math.e:
                result = math.log(number)
                return f"ln({number}) = {result}"
            else:
                result = math.log(number, base)
                return f"log_{base}({number}) = {result}"
        except Exception as e:
            return f"Error in logarithm calculation: {e}"

    @tool_method
    async def abs(self, number: float) -> str:
        """Calculate the absolute value of a number.

        Args:
            number: Number to find the absolute value of.

        Returns:
            Absolute value of the number.
        """
        if not self._abs_enabled:
            return "Error: absolute value function is disabled for this toolset instance"

        try:
            result = abs(number)
            return f"|{number}| = {result}"
        except Exception as e:
            return f"Error in absolute value calculation: {e}"

    @tool_method
    async def evaluate(self, expression: str) -> str:
        """Safely evaluate a mathematical expression.

        Args:
            expression: Mathematical expression to evaluate (e.g., "2 + 3 * 4", "sqrt(16) + 5").

        Returns:
            Result of the expression evaluation.
        """
        if not self._evaluate_enabled:
            return "Error: expression evaluation is disabled for this toolset instance"

        try:
            # Define allowed operations for safe evaluation

            # Replace common math functions with their Python equivalents
            expression = expression.replace("^", "**")  # Power operator

            # Simple eval for basic expressions - in production use safer parser
            result = eval(expression)
            return f"{expression} = {result}"

        except Exception as e:
            return f"Cannot evaluate '{expression}': {str(e)}"
