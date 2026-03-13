"""Parser for @ai-bot commands in GitLab Issue comments."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
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
    scheduled_datetime: Optional[datetime] = None  # Absolute time (takes precedence over delay_seconds)
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


def parse_scheduled_datetime(time_str: str) -> Optional[datetime]:
    """Parse human-readable time string to datetime.

    Supports:
    - at=14:30 (today at 14:30)
    - at=3pm / at=3pm (today at 15:00)
    - at=tomorrow 14:30 (tomorrow at 14:30)
    - at=tomorrow 3pm (tomorrow at 15:00)
    - at=mon 14:30 / at=monday 14:30 (next Monday at 14:30)
    - at=2026-03-14 14:30 (specific date and time)

    Args:
        time_str: Time string like "14:30", "tomorrow 3pm", "mon 14:30"

    Returns:
        datetime object or None if invalid
    """
    time_str = time_str.strip().lower()
    now = datetime.utcnow()

    # Handle "tomorrow" prefix
    is_tomorrow = time_str.startswith("tomorrow ")
    if is_tomorrow:
        time_str = time_str[9:]  # Remove "tomorrow "
        target_date = now.date() + timedelta(days=1)
    else:
        target_date = now.date()

    # Handle weekday (mon, tue, wed, thu, fri, sat, sun)
    weekday_map = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }

    weekday_match = re.match(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\s*(.*)$", time_str)
    if weekday_match:
        weekday_name = weekday_match.group(1)
        time_str = weekday_match.group(2).strip()
        target_weekday = weekday_map[weekday_name]
        current_weekday = now.weekday()
        days_until = (target_weekday - current_weekday) % 7
        if days_until == 0 and now.hour >= 12:  # If it's already past noon, next week
            days_until = 7 if not is_tomorrow else 7
        if is_tomorrow:
            days_until = 1
        target_date = now.date() + timedelta(days=days_until)

    # Parse time: "14:30", "3pm", "3:30pm", "15:00"
    hour = minute = None

    # 24-hour format: 14:30, 9:00
    match = re.match(r"(\d{1,2}):(\d{2})$", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))

    # 12-hour format: 3pm, 3:30pm, 3PM, 3:30PM
    if hour is None:
        match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            period = match.group(3).lower()
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0

    if hour is None:
        return None

    # Validate hour and minute
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    return datetime.combine(target_date, time(hour, minute))


def parse_ai_bot_command(comment_body: str) -> Optional[BotCommand]:
    """Parse @ai-bot command from a GitLab Issue comment.

    Supports formats:
    - @ai-bot <prompt>
    - @ai-bot: <prompt>
    - @ai-bot priority=high <prompt>
    - @ai-bot priority=2 <prompt>
    - @ai-bot delay=5m <prompt>
    - @ai-bot delay=1h <prompt>
    - @ai-bot at=14:30 <prompt>
    - @ai-bot at=tomorrow 14:30 <prompt>
    - @ai-bot at=mon 9am <prompt>
    - @ai-bot cancel
    - @ai-bot status

    Args:
        comment_body: The body of the GitLab Issue comment

    Returns:
        BotCommand if found, None otherwise
    """
    # Support both @ai-bot and @ci_bot aliases
    bot_names = ["ai-bot", "ci-bot", "ci_bot"]

    # First, check for special commands (cancel, status)
    special_commands = []
    for bot in bot_names:
        special_commands.append(("@" + bot + r"\s+cancel", "cancel"))
        special_commands.append(("@" + bot + r":\s+cancel", "cancel"))
        special_commands.append(("@" + bot + r"\s+status", "status"))
        special_commands.append(("@" + bot + r":\s+status", "status"))

    for pattern, command in special_commands:
        if re.search(pattern, comment_body, re.IGNORECASE):
            return BotCommand(
                command=command,
                args="",
                raw_mention=re.search(pattern, comment_body, re.IGNORECASE).group(0),
            )

    # Support bare trigger: "@ai-bot" or "@ai-bot:" with no args.
    for bot in bot_names:
        bare_pattern = r"@" + bot + r"(?::)?\s*$"
        bare_match = re.search(bare_pattern, comment_body, re.IGNORECASE)
        if bare_match:
            return BotCommand(
                command="generate",
                args="",
                raw_mention=bare_match.group(0),
            )

    # Parse main generate command (support both @ai-bot and @ci-bot)
    patterns = []
    for bot in bot_names:
        patterns.append("@" + bot + r"\s+(.+)$")
        patterns.append("@" + bot + r":\s+(.+)$")

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

            # Scheduled time parameter (at=) - takes precedence over delay_seconds
            # Parse this LAST since at value may contain spaces (e.g., "tomorrow 14:30")
            scheduled_datetime: Optional[datetime] = None
            at_pattern = re.compile(r"\bat\s*=\s*", re.IGNORECASE)
            at_pos = at_pattern.search(args)
            if at_pos:
                remaining = args[at_pos.end():]
                at_str = None

                # 1. Try full remaining first
                result = parse_scheduled_datetime(remaining)
                if result:
                    at_str = remaining
                    scheduled_datetime = result
                else:
                    # 2. Try to find next param keyword
                    param_keywords = [' priority=', ' delay=', ' target=']
                    end_pos = len(remaining)
                    for keyword in param_keywords:
                        idx = remaining.find(keyword)
                        if idx != -1 and idx < end_pos:
                            end_pos = idx

                    test_str = remaining[:end_pos].strip()
                    result = parse_scheduled_datetime(test_str)
                    if result:
                        at_str = test_str
                        scheduled_datetime = result
                        remaining = remaining[end_pos:]

                # 3. If still no match, try different split strategies
                if not at_str:
                    # Split by spaces and try progressive combinations
                    parts = remaining.split()
                    for i in range(1, len(parts) + 1):
                        # Try first i parts as at value, rest is remaining
                        candidate = ' '.join(parts[:i])
                        result = parse_scheduled_datetime(candidate)
                        if result:
                            at_str = candidate
                            scheduled_datetime = result
                            remaining = ' '.join(parts[i:])
                            break

                if at_str and scheduled_datetime:
                    # Successfully parsed, remove at=xxx from args
                    before_at = args[:at_pos.start()]
                    args = (before_at + ' ' + remaining).strip()
                    # Clean up extra spaces
                    args = ' '.join(args.split())

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
                scheduled_datetime=scheduled_datetime,
                target_branch=target_branch,
            )

    return None
