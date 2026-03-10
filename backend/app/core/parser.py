"""Parser for @ai-bot commands in GitLab Issue comments."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# Priority levels
PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_HIGH = 2
PRIORITY_URGENT = 3

PRIORITY_MAP = {
    "low": PRIORITY_LOW,
    "normal": PRIORITY_NORMAL,
    "high": PRIORITY_HIGH,
    "urgent": PRIORITY_URGENT,
}


@dataclass
class BotCommand:
    """Parsed bot command from a GitLab Issue comment."""

    command: str
    args: str
    raw_mention: str

    # Extended fields
    priority: int = PRIORITY_NORMAL
    delay_seconds: Optional[int] = None
    target_branch: Optional[str] = None


def parse_time_delta(time_str: str) -> Optional[int]:
    """Parse time string to seconds.

    Supports:
    - 5s, 10sec, 30seconds
    - 5m, 10min, 30minutes
    - 1h, 2hours
    - 1d, 2days

    Args:
        time_str: Time string like "5m", "1h", "30s"

    Returns:
        Number of seconds or None if invalid
    """
    time_str = time_str.strip().lower()

    # Days
    match = re.match(r"(\d+)\s*(d|days?)$", time_str)
    if match:
        return int(match.group(1)) * 86400

    # Hours
    match = re.match(r"(\d+)\s*(h|hours?|hrs?)$", time_str)
    if match:
        return int(match.group(1)) * 3600

    # Minutes
    match = re.match(r"(\d+)\s*(m|minutes?|mins?)$", time_str)
    if match:
        return int(match.group(1)) * 60

    # Seconds
    match = re.match(r"(\d+)\s*(s|seconds?|secs?)$", time_str)
    if match:
        return int(match.group(1))

    return None


def parse_ai_bot_command(comment_body: str) -> Optional[BotCommand]:
    """Parse @ai-bot command from a GitLab Issue comment.

    Supports formats:
    - @ai-bot <prompt>
    - @ai-bot: <prompt>
    - @ai-bot priority=high <prompt>
    - @ai-bot priority=2 <prompt>
    - @ai-bot delay=5m <prompt>
    - @ai-bot delay=1h <prompt>
    - @ai-bot cancel
    - @ai-bot status

    Args:
        comment_body: The body of the GitLab Issue comment

    Returns:
        BotCommand if found, None otherwise
    """
    # First, check for special commands (cancel, status)
    special_commands = [
        (r"@ai-bot\s+cancel", "cancel"),
        (r"@ai-bot:\s+cancel", "cancel"),
        (r"@ai-bot\s+status", "status"),
        (r"@ai-bot:\s+status", "status"),
    ]

    for pattern, command in special_commands:
        if re.search(pattern, comment_body, re.IGNORECASE):
            return BotCommand(
                command=command,
                args="",
                raw_mention=re.search(pattern, comment_body, re.IGNORECASE).group(0),
            )

    # Parse main generate command
    patterns = [
        r"@ai-bot\s+(.+)$",
        r"@ai-bot:\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
        if match:
            args = match.group(1).strip()

            # Default values
            priority = PRIORITY_NORMAL
            delay_seconds: Optional[int] = None
            target_branch: Optional[str] = None

            # Extract parameters from the beginning of args
            # Format: @ai-bot priority=high delay=5m target=develop prompt...

            # Priority parameter
            priority_match = re.match(
                r"priority\s*=\s*(\w+)\s*(.*)$",
                args,
                re.IGNORECASE
            )
            if priority_match:
                priority_value = priority_match.group(1).lower()
                priority = PRIORITY_MAP.get(priority_value, int(priority_value) if priority_value.isdigit() else PRIORITY_NORMAL)
                args = priority_match.group(2).strip()

            # Delay parameter
            delay_match = re.match(
                r"delay\s*=\s*(\d+\s*[smhd]|minutes?|hours?|days?)\s*(.*)$",
                args,
                re.IGNORECASE
            )
            if delay_match:
                delay_str = delay_match.group(1)
                delay_seconds = parse_time_delta(delay_str)
                args = delay_match.group(2).strip()

            # Target branch parameter
            target_match = re.match(
                r"target\s*=\s*(\S+)\s*(.*)$",
                args,
                re.IGNORECASE
            )
            if target_match:
                target_branch = target_match.group(1)
                args = target_match.group(2).strip()

            return BotCommand(
                command="generate",
                args=args,
                raw_mention=match.group(0),
                priority=priority,
                delay_seconds=delay_seconds,
                target_branch=target_branch,
            )

    return None
