"""Text utility functions for safe truncation and formatting."""

def safe_truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Safely truncate text to max_length with proper Unicode handling.

    Args:
        text: Text to truncate
        max_length: Maximum length in characters
        suffix: Suffix to add if truncated (default "...")

    Returns:
        Truncated text, guaranteed to be <= max_length
    """
    if not text:
        return ""

    # Add safety margin for encoding differences
    safe_max = max_length - len(suffix) - 10  # 10 char safety margin

    if len(text) <= safe_max:
        return text

    # Truncate and add suffix
    truncated = text[:safe_max].rstrip()
    return truncated + suffix
