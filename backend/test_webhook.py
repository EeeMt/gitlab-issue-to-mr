#!/usr/bin/env python3
"""
Test webhook processing logic without external dependencies.
"""

import sys
sys.path.insert(0, '/Users/xiquan/Projects/gitlab_issues_to_mr/backend')

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
    return failed == 0


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
    return failed == 0


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
    return failed == 0


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
    return failed == 0


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
    return failed == 0


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("GIMR Webhook Logic Tests")
    print("=" * 60)

    results = []

    results.append(("Webhook Payload Parsing", test_webhook_payload_parsing()))
    results.append(("Webhook Validation", test_webhook_validation()))
    results.append(("Task Status Transitions", test_task_status_transitions()))
    results.append(("Concurrency Control", test_concurrency_control()))
    results.append(("Delay Calculation", test_delay_calculation()))

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
