#!/usr/bin/env python3
"""
Local test script to verify core logic without Docker/PostgreSQL.
Tests parser, models, and scheduler logic.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import UTC, datetime, timedelta
from app.core.parser import (
    parse_ai_bot_command,
    PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_URGENT,
)
from app.models import Task, TaskStatus


def check_parser():
    """Test command parser."""
    print("=" * 60)
    print("Testing Parser")
    print("=" * 60)

    tests = [
        # (input, expected_command, expected_args, expected_priority, expected_delay)
        ("@ai-bot hello world", "generate", "hello world", PRIORITY_NORMAL, None),
        ("@ai-bot", "generate", "", PRIORITY_NORMAL, None),
        ("@ai-bot:", "generate", "", PRIORITY_NORMAL, None),
        ("@ai-bot: create a function", "generate", "create a function", PRIORITY_NORMAL, None),
        ("@ai-bot priority=low do something", "generate", "do something", PRIORITY_LOW, None),
        ("@ai-bot priority=high urgent task", "generate", "urgent task", PRIORITY_HIGH, None),
        ("@ai-bot priority=2 do it", "generate", "do it", 2, None),
        ("@ai-bot delay=5m run later", "generate", "run later", PRIORITY_NORMAL, 300),
        ("@ai-bot delay=1h run after hour", "generate", "run after hour", PRIORITY_NORMAL, 3600),
        ("@ai-bot delay=30s quick", "generate", "quick", PRIORITY_NORMAL, 30),
        ("@ai-bot delay=2d later", "generate", "later", PRIORITY_NORMAL, 172800),
        ("@ai-bot cancel", "cancel", "", PRIORITY_NORMAL, None),
        ("@ai-bot status", "status", "", PRIORITY_NORMAL, None),
        ("@ai-bot priority=urgent delay=10m target=develop complex",
         "generate", "complex", PRIORITY_URGENT, 600),
    ]

    passed = 0
    failed = 0

    for test in tests:
        input_text, exp_cmd, exp_args, exp_priority, exp_delay = test
        cmd = parse_ai_bot_command(input_text)

        if cmd is None:
            print(f"❌ FAIL: {input_text}")
            print(f"   Expected: {exp_cmd}, Got: None")
            failed += 1
            continue

        errors = []
        if cmd.command != exp_cmd:
            errors.append(f"command: {exp_cmd} != {cmd.command}")
        if cmd.args != exp_args:
            errors.append(f"args: {exp_args} != {cmd.args}")
        if cmd.priority != exp_priority:
            errors.append(f"priority: {exp_priority} != {cmd.priority}")
        if cmd.delay_seconds != exp_delay:
            errors.append(f"delay: {exp_delay} != {cmd.delay_seconds}")

        if errors:
            print(f"❌ FAIL: {input_text}")
            for err in errors:
                print(f"   {err}")
            failed += 1
        else:
            print(f"✅ PASS: {input_text}")
            passed += 1

    print(f"\nParser Results: {passed} passed, {failed} failed")
    return failed == 0


def check_models():
    """Test data models."""
    print("\n" + "=" * 60)
    print("Testing Models")
    print("=" * 60)

    # Check TaskStatus enum
    expected_statuses = ['pending', 'queued', 'running', 'completed', 'failed', 'cancelled']
    actual_statuses = [s.value for s in TaskStatus]

    if set(expected_statuses) == set(actual_statuses):
        print("✅ PASS: TaskStatus enum correct")
    else:
        print("❌ FAIL: TaskStatus enum incorrect")
        print(f"   Expected: {expected_statuses}")
        print(f"   Got: {actual_statuses}")
        return False

    # Check Task fields
    task_fields = [c.name for c in Task.__table__.columns]
    required_fields = [
        'id', 'project_id', 'issue_iid', 'issue_id', 'note_id',
        'user_prompt', 'branch_name', 'merge_request_iid', 'merge_request_url',
        'status', 'priority', 'scheduled_at', 'container_id', 'target_branch',
        'commit_sha', 'error_message', 'created_at', 'updated_at',
        'started_at', 'completed_at'
    ]

    missing = set(required_fields) - set(task_fields)
    if missing:
        print(f"❌ FAIL: Missing fields: {missing}")
        return False
    else:
        print(f"✅ PASS: All required fields present ({len(task_fields)} fields)")

    print("✅ PASS: Models OK")
    return True


def check_task_creation():
    """Test task creation with new fields."""
    print("\n" + "=" * 60)
    print("Testing Task Creation")
    print("=" * 60)

    # Simulate task creation (without DB, defaults won't be applied)
    now = datetime.now(UTC)
    scheduled = now + timedelta(minutes=5)

    task = Task(
        project_id=123,
        issue_id=456,
        issue_iid=789,
        note_id=111,
        user_prompt="test prompt",
        branch_name="gimr/issue-789",
        priority=PRIORITY_HIGH,
        scheduled_at=scheduled,
        target_branch="develop",
        status=TaskStatus.PENDING,  # Set explicitly (would come from DB default)
    )

    assert task.status == TaskStatus.PENDING, "Default status should be PENDING"
    assert task.priority == PRIORITY_HIGH, "Priority should be HIGH"
    assert task.scheduled_at == scheduled, "Scheduled time should match"
    assert task.target_branch == "develop", "Target branch should be set"
    assert task.container_id is None, "Container ID should be None initially"

    # Test that we can set all new fields
    task.container_id = "abc123"
    assert task.container_id == "abc123"

    task.merge_request_url = "https://gitlab.example.com/!123"
    assert task.merge_request_url == "https://gitlab.example.com/!123"

    print("✅ PASS: Task creation with new fields OK")
    return True


def check_scheduler_logic():
    """Test scheduler selection logic (without DB)."""
    print("\n" + "=" * 60)
    print("Testing Scheduler Logic (Mock)")
    print("=" * 60)

    # Create mock tasks
    now = datetime.now(UTC)

    tasks = [
        # (priority, scheduled_at, status, name)
        (1, None, TaskStatus.PENDING, "normal task"),
        (2, None, TaskStatus.PENDING, "high priority"),
        (0, None, TaskStatus.PENDING, "low priority"),
        (1, now - timedelta(minutes=1), TaskStatus.PENDING, "delayed ready"),
        (1, now + timedelta(minutes=5), TaskStatus.PENDING, "delayed future"),
        (1, None, TaskStatus.RUNNING, "already running"),
        (1, None, TaskStatus.COMPLETED, "already done"),
    ]

    # Simulate scheduler query logic:
    # - status in (PENDING, QUEUED)
    # - scheduled_at <= now (or null) - will be filtered by DB
    # - order by priority DESC, scheduled_at ASC, created_at ASC
    # Note: In SQL, NULL is sorted first with ASC (smallest)

    pending_tasks = [t for t in tasks if t[2] in [TaskStatus.PENDING, TaskStatus.QUEUED]]
    ready_tasks = [t for t in pending_tasks if t[1] is None or t[1] <= now]

    # Sort by priority DESC, scheduled_at ASC (None is treated as smallest in SQL)
    ready_tasks.sort(key=lambda x: (-x[0], x[1] if x[1] else datetime.min))

    print("Ready tasks (in order):")
    for i, t in enumerate(ready_tasks):
        print(f"  {i+1}. {t[3]} (priority={t[0]}, scheduled={t[1]})")

    # Verify order: high priority first, then by scheduled (None/earlier first)
    # Note: None means "execute immediately", so it comes before past scheduled times
    expected_order = ["high priority", "normal task", "delayed ready", "low priority"]
    actual_order = [t[3] for t in ready_tasks]

    if actual_order == expected_order:
        print("✅ PASS: Scheduler priority logic correct")
    else:
        print("❌ FAIL: Scheduler priority logic incorrect")
        print(f"   Expected: {expected_order}")
        print(f"   Got: {actual_order}")
        return False

    return True


def check_issue_mutex():
    """Test issue-level mutex logic."""
    print("\n" + "=" * 60)
    print("Testing Issue Mutex Logic")
    print("=" * 60)

    # Simulate running issues
    running_issues = set()

    # Try to schedule tasks for same issue
    test_cases = [
        ("123:456", True),   # First task for issue - should run
        ("123:456", False),  # Second task for same issue - should block
        ("789:101", True),   # Different issue - should run
        ("123:456", False),  # Third task - should block
    ]

    for issue_key, expected in test_cases:
        can_run = issue_key not in running_issues
        if can_run:
            running_issues.add(issue_key)

        status = "✅ ALLOW" if can_run else "❌ BLOCK"
        expected_str = "✅" if can_run == expected else "❌"
        print(f"  {status} task for {issue_key} (expected {expected_str})")

        if can_run != expected:
            print(f"   ❌ FAIL: Expected {expected}, got {can_run}")
            return False

    print("✅ PASS: Issue mutex logic correct")
    return True


def check_issue_context_prompt_builders():
    """Test issue-context prompt helpers for generic and explicit prompts."""
    print("\n" + "=" * 60)
    print("Testing Issue Context Prompt Builders")
    print("=" * 60)

    from app.api.webhook import build_enhanced_prompt, build_prompt_with_issue_context

    title = "Implement search API"
    desc = "Need pagination and fuzzy matching"

    generic_prompt = build_enhanced_prompt("", title, desc)
    if "Issue: Implement search API" not in generic_prompt or "Need pagination and fuzzy matching" not in generic_prompt:
        print("❌ FAIL: build_enhanced_prompt missing issue context")
        return False

    combined = build_prompt_with_issue_context("Please use FastAPI", title, desc)
    if "用户补充要求" not in combined or "Please use FastAPI" not in combined:
        print("❌ FAIL: build_prompt_with_issue_context missing user prompt section")
        return False
    if "Issue: Implement search API" not in combined or "Need pagination and fuzzy matching" not in combined:
        print("❌ FAIL: build_prompt_with_issue_context missing issue context")
        return False

    print("✅ PASS: Issue context prompt builders correct")
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("GIMR P1 - Local Tests")
    print("=" * 60)

    results = []

    results.append(("Parser", check_parser()))
    results.append(("Models", check_models()))
    results.append(("Task Creation", check_task_creation()))
    results.append(("Scheduler Logic", check_scheduler_logic()))
    results.append(("Issue Mutex", check_issue_mutex()))
    results.append(("Issue Context Prompt Builders", check_issue_context_prompt_builders()))

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
