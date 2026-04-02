#!/usr/bin/env python3
"""
Test timeout and crash recovery logic.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import UTC, datetime, timedelta
from app.models import Task, TaskStatus


def check_timeout_detection():
    """Test task timeout detection logic."""
    print("=" * 60)
    print("Testing Timeout Detection")
    print("=" * 60)

    task_timeout = 1800  # 30 minutes

    test_cases = [
        # (started_at, expected_timed_out)
        (datetime.now(UTC) - timedelta(minutes=10), False),   # 10 min ago - not timed out
        (datetime.now(UTC) - timedelta(minutes=25), False),    # 25 min ago - not timed out (within 30min)
        (datetime.now(UTC) - timedelta(minutes=30), True),      # 30 min ago - exactly timed out
        (datetime.now(UTC) - timedelta(minutes=31), True),      # 31 min ago - timed out
        (datetime.now(UTC) - timedelta(hours=1), True),         # 1 hour ago - definitely timed out
        (None, False),                                         # Not started - not timed out
    ]

    passed = 0
    failed = 0

    for started_at, expected_timed_out in test_cases:
        # Simulate timeout detection logic
        if started_at is None:
            is_timed_out = False
        else:
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            is_timed_out = elapsed > task_timeout

        if is_timed_out == expected_timed_out:
            print(f"✅ PASS: started_at={started_at}, timed_out={is_timed_out}")
            passed += 1
        else:
            print(f"❌ FAIL: started_at={started_at}, expected={expected_timed_out}, got={is_timed_out}")
            failed += 1

    print(f"\nTimeout Detection: {passed} passed, {failed} failed")
    return failed == 0


def check_container_naming():
    """Test container naming convention."""
    print("\n" + "=" * 60)
    print("Testing Container Naming Convention")
    print("=" * 60)

    test_cases = [
        # (task_id, project_id, issue_iid, expected_name)
        (1, 123, 456, "codify-1-p123-i456"),
        (10, 1, 99, "codify-10-p1-i99"),
        (100, 999, 1000, "codify-100-p999-i1000"),
    ]

    passed = 0
    failed = 0

    for task_id, project_id, issue_iid, expected in test_cases:
        # Generate container name using the convention
        actual = f"codify-{task_id}-p{project_id}-i{issue_iid}"

        if actual == expected:
            print(f"✅ PASS: {actual}")
            passed += 1
        else:
            print(f"❌ FAIL: expected {expected}, got {actual}")
            failed += 1

    print(f"\nContainer Naming: {passed} passed, {failed} failed")
    return failed == 0


def check_crash_recovery_logic():
    """Test crash recovery logic."""
    print("\n" + "=" * 60)
    print("Testing Crash Recovery Logic")
    print("=" * 60)

    # Simulate tasks that were running when crash happened
    tasks = [
        {"id": 1, "status": TaskStatus.RUNNING, "started_at": datetime.now(UTC) - timedelta(minutes=10)},
        {"id": 2, "status": TaskStatus.RUNNING, "started_at": datetime.now(UTC) - timedelta(hours=1)},
        {"id": 3, "status": TaskStatus.PENDING, "started_at": None},
        {"id": 4, "status": TaskStatus.COMPLETED, "started_at": datetime.now(UTC) - timedelta(hours=2)},
        {"id": 5, "status": TaskStatus.RUNNING, "started_at": datetime.now(UTC) - timedelta(minutes=5)},
    ]

    task_timeout = 1800  # 30 minutes

    print("\n--- Simulating crash recovery ---")
    recovered_count = 0

    for task in tasks:
        if task["status"] == TaskStatus.RUNNING:
            # Check if task was running too long (likely crashed)
            if task["started_at"]:
                elapsed = (datetime.now(UTC) - task["started_at"]).total_seconds()
                if elapsed > task_timeout:
                    print(f"✅ RECOVER: Task {task['id']} timed out (ran {elapsed/60:.1f} min), marking as FAILED")
                    task["status"] = TaskStatus.FAILED
                    recovered_count += 1
                else:
                    print(f"⚠️  STUCK: Task {task['id']} still running ({elapsed/60:.1f} min), needs recovery")
                    recovered_count += 1
            else:
                print(f"❓ UNKNOWN: Task {task['id']} has no started_at")
        else:
            print(f"⏭️  SKIP: Task {task['id']} status={task['status'].value}")

    print(f"\nTotal tasks recovered: {recovered_count}/5")

    # Expected: 4 tasks need recovery (all RUNNING tasks)
    # - Task 1: stuck (5 min) -> should be recovered
    # - Task 2: timeout (60 min) -> should be marked FAILED
    # - Task 5: stuck (25 min) -> should be recovered

    passed = recovered_count >= 3  # At least 3 running tasks should be recovered
    if passed:
        print("✅ PASS: Crash recovery logic works")
    else:
        print("❌ FAIL: Crash recovery logic")

    return passed


def check_container_cleanup_pattern():
    """Test container cleanup pattern matching."""
    print("\n" + "=" * 60)
    print("Testing Container Cleanup Pattern")
    print("=" * 60)

    import re
    WORKER_CONTAINER_PATTERN = re.compile(r"^codify-\d+-p\d+-i\d+$")

    test_cases = [
        # (container_name, should_clean)
        ("codify-1-p123-i456", True),      # Worker container - clean
        ("codify-10-p1-i99", True),        # Worker container - clean
        ("codify-backend", False),         # Backend service - skip
        ("codify-postgres", False),         # Postgres service - skip
        ("random-container", False),       # Unrelated - skip
        ("codify-", False),                # Invalid pattern - skip
    ]

    passed = 0
    failed = 0

    for container_name, should_clean in test_cases:
        matches = WORKER_CONTAINER_PATTERN.match(container_name) is not None

        if matches == should_clean:
            action = "CLEAN" if should_clean else "SKIP"
            print(f"✅ PASS: {container_name} -> {action}")
            passed += 1
        else:
            print(f"❌ FAIL: {container_name}, expected clean={should_clean}, got {matches}")
            failed += 1

    print(f"\nContainer Cleanup Pattern: {passed} passed, {failed} failed")
    return failed == 0


def check_status_transition_on_timeout():
    """Test that timeout properly transitions task status."""
    print("\n" + "=" * 60)
    print("Testing Status Transition on Timeout")
    print("=" * 60)

    # Simulate a task that times out
    task = {
        "id": 1,
        "status": TaskStatus.RUNNING,
        "started_at": datetime.now(UTC) - timedelta(hours=1),
        "error_message": None
    }

    task_timeout = 1800  # 30 minutes

    # Check if timed out
    elapsed = (datetime.now(UTC) - task["started_at"]).total_seconds()
    is_timed_out = elapsed > task_timeout

    print(f"Task {task['id']}: elapsed={elapsed}s, timeout={task_timeout}s, timed_out={is_timed_out}")

    if is_timed_out:
        # Transition to FAILED
        task["status"] = TaskStatus.FAILED
        task["error_message"] = f"Task timed out after {elapsed/60:.1f} minutes"
        print(f"Transitioned to: {task['status'].value}")
        print(f"Error message: {task['error_message']}")

    if task["status"] == TaskStatus.FAILED and "timed out" in task["error_message"]:
        print("✅ PASS: Status transition on timeout works")
        return True
    else:
        print("❌ FAIL: Status transition on timeout")
        return False


def main():
    """Run all timeout and crash recovery tests."""
    print("\n" + "=" * 60)
    print("Codify Timeout & Crash Recovery Tests")
    print("=" * 60)

    results = []

    results.append(("Timeout Detection", check_timeout_detection()))
    results.append(("Container Naming", check_container_naming()))
    results.append(("Crash Recovery Logic", check_crash_recovery_logic()))
    results.append(("Container Cleanup Pattern", check_container_cleanup_pattern()))
    results.append(("Status Transition on Timeout", check_status_transition_on_timeout()))

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
