"""Utility functions for AgentArea CLI."""

import re
from typing import Any, List, Optional

from .exceptions import ValidationError


def format_table(headers: List[str], rows: List[List[str]], max_width: int = 120) -> str:
    """Format data as a table with proper alignment and spacing.
    
    Args:
        headers: List of column headers
        rows: List of rows, where each row is a list of strings
        max_width: Maximum width for the entire table
    
    Returns:
        Formatted table as a string
    """
    if not headers or not rows:
        return ""
    
    # Calculate column widths
    col_widths = [len(header) for header in headers]
    
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Adjust widths if table is too wide
    total_width = sum(col_widths) + len(headers) * 3 + 1  # 3 chars per separator + 1 for end
    if total_width > max_width:
        # Reduce widths proportionally, but keep minimum of 10 chars per column
        reduction_factor = (max_width - len(headers) * 3 - 1) / sum(col_widths)
        col_widths = [max(10, int(width * reduction_factor)) for width in col_widths]
    
    # Build table
    lines = []
    
    # Header separator
    separator = "+" + "+".join("-" * (width + 2) for width in col_widths) + "+"
    lines.append(separator)
    
    # Header row
    header_row = "|"
    for i, header in enumerate(headers):
        if i < len(col_widths):
            header_row += f" {header:<{col_widths[i]}} |"
    lines.append(header_row)
    lines.append(separator)
    
    # Data rows
    for row in rows:
        data_row = "|"
        for i, cell in enumerate(row):
            if i < len(col_widths):
                cell_str = str(cell)
                # Truncate if too long
                if len(cell_str) > col_widths[i]:
                    cell_str = cell_str[:col_widths[i]-3] + "..."
                data_row += f" {cell_str:<{col_widths[i]}} |"
        lines.append(data_row)
    
    # Bottom separator
    lines.append(separator)
    
    return "\n".join(lines)


def safe_get_field(data: dict, field: str, default: Any = None) -> Any:
    """Safely get a field from a dictionary with a default value.
    
    Args:
        data: Dictionary to get field from
        field: Field name (supports dot notation for nested fields)
        default: Default value if field is not found
    
    Returns:
        Field value or default
    """
    if not isinstance(data, dict):
        return default
    
    # Handle dot notation for nested fields
    if "." in field:
        keys = field.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    
    return data.get(field, default)


def validate_required_field(value: Any, field_name: str) -> None:
    """Validate that a required field has a value.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
    
    Raises:
        ValidationError: If the field is empty or None
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"Field '{field_name}' is required")


def validate_email(email: str) -> bool:
    """Validate email format.
    
    Args:
        email: Email address to validate
    
    Returns:
        True if email is valid, False otherwise
    """
    if not email:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_url(url: str) -> bool:
    """Validate URL format.
    
    Args:
        url: URL to validate
    
    Returns:
        True if URL is valid, False otherwise
    """
    if not url:
        return False
    
    pattern = r'^https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})?(?::[0-9]+)?(?:/.*)?$'
    return bool(re.match(pattern, url))


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate a string to a maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncating
    
    Returns:
        Truncated string
    """
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def format_bytes(bytes_value: int) -> str:
    """Format bytes as human-readable string.
    
    Args:
        bytes_value: Number of bytes
    
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    if bytes_value == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(bytes_value)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


def format_duration(seconds: float) -> str:
    """Format duration in seconds as human-readable string.
    
    Args:
        seconds: Duration in seconds
    
    Returns:
        Formatted string (e.g., "2h 30m 15s")
    """
    if seconds < 0:
        return "0s"
    
    units = [
        ("d", 86400),  # days
        ("h", 3600),   # hours
        ("m", 60),     # minutes
        ("s", 1)       # seconds
    ]
    
    parts = []
    remaining = int(seconds)
    
    for unit_name, unit_seconds in units:
        if remaining >= unit_seconds:
            count = remaining // unit_seconds
            remaining %= unit_seconds
            parts.append(f"{count}{unit_name}")
    
    if not parts:
        return "0s"
    
    return " ".join(parts)


def parse_key_value_pairs(pairs: List[str]) -> dict:
    """Parse key=value pairs from a list of strings.
    
    Args:
        pairs: List of strings in format "key=value"
    
    Returns:
        Dictionary of parsed key-value pairs
    
    Raises:
        ValidationError: If any pair is not in correct format
    """
    result = {}
    
    for pair in pairs:
        if "=" not in pair:
            raise ValidationError(f"Invalid key=value pair: '{pair}'")
        
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        
        if not key:
            raise ValidationError(f"Empty key in pair: '{pair}'")
        
        result[key] = value
    
    return result


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by removing invalid characters.
    
    Args:
        filename: Original filename
    
    Returns:
        Sanitized filename
    """
    # Remove invalid characters
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, "_", filename)
    
    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip(". ")
    
    # Ensure it's not empty
    if not sanitized:
        sanitized = "untitled"
    
    return sanitized


def confirm_action(message: str, default: bool = False) -> bool:
    """Ask user for confirmation with a custom message.
    
    Args:
        message: Confirmation message
        default: Default value if user just presses Enter
    
    Returns:
        True if user confirms, False otherwise
    """
    suffix = " [Y/n]" if default else " [y/N]"
    
    try:
        response = input(f"{message}{suffix}: ").strip().lower()
        
        if not response:
            return default
        
        return response in ["y", "yes", "true", "1"]
    
    except (KeyboardInterrupt, EOFError):
        return False


def get_status_emoji(status: str) -> str:
    """Get emoji for a status string.
    
    Args:
        status: Status string
    
    Returns:
        Appropriate emoji
    """
    status_lower = status.lower()
    
    status_map = {
        "active": "✅",
        "inactive": "❌",
        "running": "🟢",
        "stopped": "🔴",
        "pending": "🟡",
        "error": "❌",
        "success": "✅",
        "warning": "⚠️",
        "healthy": "💚",
        "unhealthy": "💔",
        "online": "🟢",
        "offline": "🔴",
        "available": "✅",
        "unavailable": "❌"
    }
    
    return status_map.get(status_lower, "❓")


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    """Return singular or plural form based on count.
    
    Args:
        count: Number to check
        singular: Singular form
        plural: Plural form (defaults to singular + 's')
    
    Returns:
        Appropriate form with count
    """
    if plural is None:
        plural = singular + "s"
    
    word = singular if count == 1 else plural
    return f"{count} {word}"


def mask_sensitive_value(value: str, mask_char: str = "*", visible_chars: int = 4) -> str:
    """Mask sensitive values like API keys or tokens.
    
    Args:
        value: Value to mask
        mask_char: Character to use for masking
        visible_chars: Number of characters to show at the end
    
    Returns:
        Masked value
    """
    if not value or len(value) <= visible_chars:
        return mask_char * 8  # Default masked length
    
    masked_length = len(value) - visible_chars
    return mask_char * masked_length + value[-visible_chars:]


def highlight_search_term(text: str, search_term: str, highlight_color: str = "yellow") -> str:
    """Highlight search terms in text (for terminal output).
    
    Args:
        text: Text to search in
        search_term: Term to highlight
        highlight_color: Color for highlighting
    
    Returns:
        Text with highlighted search terms
    """
    if not search_term or search_term not in text.lower():
        return text
    
    # Simple highlighting for terminal (could be enhanced with click.style)
    # For now, just wrap with brackets
    pattern = re.compile(re.escape(search_term), re.IGNORECASE)
    return pattern.sub(f"[{search_term}]", text)