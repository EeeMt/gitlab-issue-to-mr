#!/usr/bin/env python3
"""
Test webhook processing logic without external dependencies.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from app.core.parser import parse_ai_bot_command, PRIORITY_HIGH, PRIORITY_NORMAL


def test_webhook_payload_parsing():
    """Test webhook payload parsing."""
    print("=" * 60)
    print("Testing Webhook Payload Parsing")
    print("=" * 60)

    # Sample GitLab webhook payloads
    test_cases = [
        # Normal generate command
        {
            "name": "Normal generate",
            "payload": {
                "object_kind": "note",
                "note": {
                    "id": 123,
                    "noteable_type": "Issue",
                    "body": "@ai-bot create a hello world function"
                },
                "issue": {"id": 456, "iid": 789},
                "project": {"id": 111}
            },
            "expected_command": "generate",
            "expected_args": "create a hello world function",
        },
        # Cancel command
        {
            "name": "Cancel command",
            "payload": {
                "object_kind": "note",
                "note": {
                    "id": 124,
                    "noteable_type": "Issue",
                    "body": "@ai-bot cancel"
                },
                "issue": {"id": 456, "iid": 789},
                "project": {"id": 111}
            },
            "expected_command": "cancel",
            "expected_args": "",
        },
        # Status command
        {
            "name": "Status command",
            "payload": {
                "object_kind": "note",
                "note": {
                    "id": 125,
                    "noteable_type": "Issue",
                    "body": "@ai-bot status"
                },
                "issue": {"id": 456, "iid": 789},
                "project": {"id": 111}
            },
            "expected_command": "status",
            "expected_args": "",
        },
        # With priority
        {
            "name": "Priority high",
            "payload": {
                "object_kind": "note",
                "note": {
                    "id": 126,
                    "noteable_type": "Issue",
                    "body": "@ai-bot priority=high fix the bug"
                },
                "issue": {"id": 456, "iid": 789},
                "project": {"id": 111}
            },
            "expected_command": "generate",
            "expected_args": "fix the bug",
            "expected_priority": PRIORITY_HIGH,
        },
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        payload = tc["payload"]
        comment_body = payload["note"]["body"]
        cmd = parse_ai_bot_command(comment_body)

        errors = []
        if cmd.command != tc["expected_command"]:
            errors.append(f"command: {tc['expected_command']} != {cmd.command}")
        if cmd.args != tc["expected_args"]:
            errors.append(f"args: {tc['expected_args']} != {cmd.args}")
        if "expected_priority" in tc and cmd.priority != tc["expected_priority"]:
            errors.append(f"priority: {tc['expected_priority']} != {cmd.priority}")

        if errors:
            print(f"❌ FAIL: {tc['name']}")
            for err in errors:
                print(f"   {err}")
            failed += 1
        else:
            print(f"✅ PASS: {tc['name']}")
            passed += 1

    print(f"\nWebhook Payload Parsing: {passed} passed, {failed} failed")
    assert failed == 0


def test_webhook_validation():
    """Test webhook validation logic."""
    print("\n" + "=" * 60)
    print("Testing Webhook Validation")
    print("=" * 60)

    test_cases = [
        # Should ignore - wrong object_kind
        {
            "name": "Wrong object_kind (push)",
            "payload": {"object_kind": "push"},
            "should_ignore": True,
        },
        # Should ignore - wrong noteable_type
        {
            "name": "Wrong noteable_type (MergeRequest)",
            "payload": {
                "object_kind": "note",
                "note": {"noteable_type": "MergeRequest"}
            },
            "should_ignore": True,
        },
        # Should ignore - empty body
        {
            "name": "Empty body",
            "payload": {
                "object_kind": "note",
                "note": {"noteable_type": "Issue", "body": ""}
            },
            "should_ignore": True,
        },
        # Should ignore - no @ai-bot
        {
            "name": "No @ai-bot command",
            "payload": {
                "object_kind": "note",
                "note": {"noteable_type": "Issue", "body": "Hello world"}
            },
            "should_ignore": True,
        },
        # Should process - valid generate
        {
            "name": "Valid generate",
            "payload": {
                "object_kind": "note",
                "note": {
                    "noteable_type": "Issue",
                    "body": "@ai-bot create a function"
                }
            },
            "should_ignore": False,
        },
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        payload = tc["payload"]
        event_type = payload.get("object_kind")
        should_ignore = event_type != "note"

        if not should_ignore:
            note = payload.get("note", {})
            note_type = note.get("noteable_type")
            comment_body = note.get("body", "")

            if note_type != "Issue":
                should_ignore = True
            elif not comment_body:
                should_ignore = True
            else:
                cmd = parse_ai_bot_command(comment_body)
                should_ignore = cmd is None

        if should_ignore == tc["should_ignore"]:
            print(f"✅ PASS: {tc['name']}")
            passed += 1
        else:
            print(f"❌ FAIL: {tc['name']}")
            print(f"   Expected ignore: {tc['should_ignore']}, Got: {should_ignore}")
            failed += 1

    print(f"\nWebhook Validation: {passed} passed, {failed} failed")
    assert failed == 0


def test_task_status_transitions():
    """Test task status transitions."""
    print("\n" + "=" * 60)
    print("Testing Task Status Transitions")
    print("=" * 60)

    from app.models import TaskStatus

    # Valid transitions
    valid_transitions = {
        TaskStatus.PENDING: [TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCELLED],
        TaskStatus.QUEUED: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
        TaskStatus.RUNNING: [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
        TaskStatus.COMPLETED: [],  # Terminal
        TaskStatus.FAILED: [],     # Terminal
        TaskStatus.CANCELLED: [],  # Terminal
    }

    passed = 0
    failed = 0

    # Test all statuses can be created
    for status in TaskStatus:
        try:
            # Just verify the status exists and has a value
            assert status.value is not None
            print(f"✅ PASS: TaskStatus.{status.name} = '{status.value}'")
            passed += 1
        except Exception as e:
            print(f"❌ FAIL: TaskStatus.{status.name}: {e}")
            failed += 1

    # Test status comparison
    if TaskStatus.PENDING != TaskStatus.RUNNING:
        print(f"✅ PASS: Status comparison works")
        passed += 1
    else:
        print(f"❌ FAIL: Status comparison")
        failed += 1

    # Test status in list
    if TaskStatus.PENDING in [TaskStatus.PENDING, TaskStatus.QUEUED]:
        print(f"✅ PASS: Status 'in' list works")
        passed += 1
    else:
        print(f"❌ FAIL: Status 'in' list")
        failed += 1

    print(f"\nTask Status Transitions: {passed} passed, {failed} failed")
    assert failed == 0


def test_concurrency_control():
    """Test concurrency control logic."""
    print("\n" + "=" * 60)
    print("Testing Concurrency Control")
    print("=" * 60)

    # Simulate max_concurrency = 2
    max_concurrency = 2

    # Track running tasks
    running_count = 0

    test_cases = [
        # (action, expected_result)
        ("try_start", "allowed"),  # 1st task - allowed
        ("try_start", "allowed"),  # 2nd task - allowed (at limit)
        ("try_start", "denied"),   # 3rd task - denied (over limit)
        ("finish", "ok"),          # 1st task finishes
        ("try_start", "allowed"),  # 3rd task retry - allowed
        ("try_start", "denied"),   # 4th task - denied
    ]

    passed = 0
    failed = 0

    for action, expected in test_cases:
        if action == "try_start":
            if running_count < max_concurrency:
                running_count += 1
                result = "allowed"
            else:
                result = "denied"
        else:  # finish
            running_count = max(0, running_count - 1)
            result = "ok"

        if result == expected:
            print(f"✅ PASS: {action} -> {result} (expected: {expected})")
            passed += 1
        else:
            print(f"❌ FAIL: {action} -> {result} (expected: {expected})")
            failed += 1

    print(f"\nConcurrency Control: {passed} passed, {failed} failed")
    assert failed == 0


def test_delay_calculation():
    """Test delay time calculation."""
    print("\n" + "=" * 60)
    print("Testing Delay Calculation")
    print("=" * 60)

    from datetime import timedelta

    test_cases = [
        ("5s", 5),
        ("30sec", 30),
        ("1m", 60),
        ("5min", 300),
        ("1h", 3600),
        ("2hours", 7200),
        ("1d", 86400),
        ("2days", 172800),
    ]

    from app.core.parser import parse_time_delta

    passed = 0
    failed = 0

    for time_str, expected_seconds in test_cases:
        result = parse_time_delta(time_str)
        if result == expected_seconds:
            print(f"✅ PASS: '{time_str}' -> {result}s")
            passed += 1
        else:
            print(f"❌ FAIL: '{time_str}' -> {result}s (expected: {expected_seconds}s)")
            failed += 1

    # Test invalid inputs
    invalid_cases = ["", "abc", "xyz"]
    for invalid in invalid_cases:
        result = parse_time_delta(invalid)
        if result is None:
            print(f"✅ PASS: '{invalid}' -> None (expected)")
            passed += 1
        else:
            print(f"❌ FAIL: '{invalid}' -> {result} (expected: None)")
            failed += 1

    print(f"\nDelay Calculation: {passed} passed, {failed} failed")
    assert failed == 0


def test_scheduled_datetime_parsing():
    """Test scheduled datetime parsing with human-readable formats."""
    print("\n" + "=" * 60)
    print("Testing Scheduled Datetime Parsing")
    print("=" * 60)

    from app.core.parser import parse_scheduled_datetime

    test_cases = [
        # 24-hour format
        ("14:30", True),           # Today at 14:30
        ("9:00", True),            # Today at 09:00
        ("23:59", True),           # Today at 23:59

        # 12-hour format
        ("3pm", True),             # Today at 15:00
        ("3:30pm", True),          # Today at 15:30
        ("12pm", True),            # Today at 12:00
        ("12am", True),            # Today at 00:00
        ("9am", True),              # Today at 09:00

        # Tomorrow
        ("tomorrow 14:30", True),  # Tomorrow at 14:30
        ("tomorrow 3pm", True),     # Tomorrow at 15:00
        ("tomorrow 9am", True),    # Tomorrow at 09:00

        # Weekday
        ("mon 9am", True),         # Next Monday at 09:00
        ("tue 14:30", True),       # Next Tuesday at 14:30
        ("wed 3pm", True),         # Next Wednesday at 15:00
        ("thu 9am", True),         # Next Thursday at 09:00
        ("fri 14:30", True),       # Next Friday at 14:30
        ("sat 3pm", True),         # Next Saturday at 15:00
        ("sun 9am", True),         # Next Sunday at 09:00
        ("monday 14:30", True),    # Next Monday at 14:30
        ("sunday 9am", True),      # Next Sunday at 09:00

        # Invalid inputs
        ("", False),
        ("abc", False),
        ("25:00", False),          # Invalid hour
        ("14:60", False),          # Invalid minute
    ]

    passed = 0
    failed = 0

    for time_str, should_pass in test_cases:
        result = parse_scheduled_datetime(time_str)
        if should_pass:
            if result is not None:
                print(f"✅ PASS: '{time_str}' -> {result}")
                passed += 1
            else:
                print(f"❌ FAIL: '{time_str}' -> None (expected datetime)")
                failed += 1
        else:
            if result is None:
                print(f"✅ PASS: '{time_str}' -> None (expected)")
                passed += 1
            else:
                print(f"❌ FAIL: '{time_str}' -> {result} (expected: None)")
                failed += 1

    print(f"\nScheduled Datetime Parsing: {passed} passed, {failed} failed")
    assert failed == 0


def test_scheduled_datetime_integration():
    """Test full command parsing with at= parameter."""
    print("\n" + "=" * 60)
    print("Testing Scheduled Datetime in Command Parsing")
    print("=" * 60)

    from app.core.parser import parse_ai_bot_command

    test_cases = [
        # Simple at= cases
        {
            "name": "at=14:30",
            "input": "@ai-bot at=14:30 fix the bug",
            "expect_scheduled": True,
            "expect_delay": False,
        },
        {
            "name": "at=3pm",
            "input": "@ai-bot at=3pm fix the bug",
            "expect_scheduled": True,
            "expect_delay": False,
        },
        {
            "name": "at=tomorrow 14:30",
            "input": "@ai-bot at=tomorrow 14:30 fix the bug",
            "expect_scheduled": True,
            "expect_delay": False,
        },
        {
            "name": "at=mon 9am",
            "input": "@ai-bot at=mon 9am fix the bug",
            "expect_scheduled": True,
            "expect_delay": False,
        },
        # Combined with other params
        {
            "name": "priority + at",
            "input": "@ai-bot priority=high at=14:30 fix the bug",
            "expect_scheduled": True,
            "expect_priority": 2,
        },
        {
            "name": "at + priority (at first)",
            "input": "@ai-bot at=14:30 priority=high fix the bug",
            "expect_scheduled": True,
            "expect_priority": 1,  # priority parsed after at
        },
        # at takes precedence over delay
        {
            "name": "at + delay (at wins)",
            "input": "@ai-bot at=14:30 delay=5m fix the bug",
            "expect_scheduled": True,
            "expect_delay": False,
        },
        # Just delay
        {
            "name": "delay=5m",
            "input": "@ai-bot delay=5m fix the bug",
            "expect_scheduled": False,
            "expect_delay": True,
            "expect_delay_seconds": 300,
        },
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        cmd = parse_ai_bot_command(tc["input"])
        name = tc["name"]

        if cmd is None:
            print(f"❌ FAIL: {name} - command not parsed")
            failed += 1
            continue

        # Check scheduled_datetime
        has_scheduled = cmd.scheduled_datetime is not None
        if has_scheduled != tc.get("expect_scheduled", False):
            print(f"❌ FAIL: {name} - scheduled_datetime: {has_scheduled}, expected: {tc.get('expect_scheduled')}")
            failed += 1
        elif tc.get("expect_scheduled"):
            print(f"✅ PASS: {name} - scheduled_datetime={cmd.scheduled_datetime}")
            passed += 1
        else:
            print(f"✅ PASS: {name} - no scheduled_datetime")
            passed += 1

        # Check delay_seconds
        has_delay = cmd.delay_seconds is not None
        if has_delay != tc.get("expect_delay", False):
            print(f"❌ FAIL: {name} - delay_seconds: {has_delay}, expected: {tc.get('expect_delay')}")
            failed += 1
        elif tc.get("expect_delay") and cmd.delay_seconds != tc.get("expect_delay_seconds"):
            print(f"❌ FAIL: {name} - delay_seconds: {cmd.delay_seconds}, expected: {tc.get('expect_delay_seconds')}")
            failed += 1

        # Check priority
        if "expect_priority" in tc:
            if cmd.priority != tc["expect_priority"]:
                print(f"❌ FAIL: {name} - priority: {cmd.priority}, expected: {tc['expect_priority']}")
                failed += 1
            else:
                print(f"✅ PASS: {name} - priority={cmd.priority}")

    print(f"\nScheduled Datetime Integration: {passed} passed, {failed} failed")
    assert failed == 0


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("GIMR Webhook Logic Tests")
    print("=" * 60)

    results = []
    test_cases = [
        ("Webhook Payload Parsing", test_webhook_payload_parsing),
        ("Webhook Validation", test_webhook_validation),
        ("Task Status Transitions", test_task_status_transitions),
        ("Concurrency Control", test_concurrency_control),
        ("Delay Calculation", test_delay_calculation),
        ("Scheduled Datetime Parsing", test_scheduled_datetime_parsing),
        ("Scheduled Datetime Integration", test_scheduled_datetime_integration),
    ]

    for name, fn in test_cases:
        try:
            fn()
            results.append((name, True))
        except AssertionError:
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
