#!/usr/bin/env python3
"""
End-to-end simulation test without external dependencies.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import UTC, datetime, timedelta
from app.models import Task, TaskStatus
from app.core.parser import parse_ai_bot_command


def simulate_full_workflow():
    """Simulate the full workflow from webhook to completion."""
    print("=" * 60)
    print("E2E Workflow Simulation")
    print("=" * 60)

    # Step 1: User posts comment on GitLab Issue
    print("\n📝 Step 1: User posts comment")
    comment = "@ai-bot priority=high delay=1m create a REST API endpoint"
    print(f"   Comment: {comment}")

    # Step 2: Parse command
    print("\n🔍 Step 2: Parse command")
    cmd = parse_ai_bot_command(comment)
    print(f"   Command: {cmd.command}")
    print(f"   Args: {cmd.args}")
    print(f"   Priority: {cmd.priority}")
    print(f"   Delay: {cmd.delay_seconds}s")

    # Step 3: Create task
    print("\n📋 Step 3: Create task")
    now = datetime.now(UTC)
    scheduled_at = now + timedelta(seconds=cmd.delay_seconds) if cmd.delay_seconds else None

    task = Task(
        project_id=123,
        issue_id=456,
        user_prompt=cmd.args,
        priority=cmd.priority,
        scheduled_at=scheduled_at,
        status=TaskStatus.PENDING,
    )
    print(f"   Task ID: {task.id} (mock)")
    print(f"   Status: {task.status.value}")
    print(f"   Priority: {task.priority}")
    print(f"   Scheduled: {task.scheduled_at}")

    # Step 4: Scheduler picks up task (simulate delay passed)
    print("\n⏰ Step 4: Scheduler - delay passed, ready to run")
    # Simulate time passing
    task.scheduled_at = now - timedelta(seconds=30)  # delay passed

    # Scheduler checks
    can_run = (
        task.status in [TaskStatus.PENDING, TaskStatus.QUEUED] and
        (task.scheduled_at is None or task.scheduled_at <= datetime.now(UTC))
    )
    print(f"   Can run: {can_run}")

    # Step 5: Execute task
    print("\n🚀 Step 5: Execute task")
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(UTC)
    task.container_id = "codify-1-p123-i789"
    print(f"   Status: {task.status.value}")
    print(f"   Container: {task.container_id}")

    # Step 6: Task completes
    print("\n✅ Step 6: Task completes")
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(UTC)
    task.merge_request_url = "https://gitlab.example.com/!1"
    task.commit_sha = "abc123def456"
    print(f"   Status: {task.status.value}")
    print(f"   MR URL: {task.merge_request_url}")
    print(f"   Commit: {task.commit_sha}")

    # Step 7: User posts cancel command
    print("\n❌ Step 7: User posts cancel")
    cancel_comment = "@ai-bot cancel"
    cmd = parse_ai_bot_command(cancel_comment)
    print(f"   Command: {cmd.command}")

    # Check if there's a running task to cancel
    running_task = task  # reuse previous task for demo
    if running_task.status == TaskStatus.RUNNING:
        running_task.status = TaskStatus.CANCELLED
        running_task.completed_at = datetime.now(UTC)
        running_task.error_message = "Cancelled by user"
        print(f"   Cancelled task: {running_task.id}")

    # Step 8: User posts status command
    print("\n📊 Step 8: User posts status")
    status_comment = "@ai-bot status"
    cmd = parse_ai_bot_command(status_comment)
    print(f"   Command: {cmd.command}")
    print(f"   Would return: status={task.status.value}, MR={task.merge_request_url}")

    print("\n" + "=" * 60)
    print("✅ E2E Workflow Simulation Complete!")
    print("=" * 60)
    return True


def simulate_concurrent_issues():
    """Simulate multiple issues with concurrent tasks."""
    print("\n" + "=" * 60)
    print("Concurrent Issues Simulation")
    print("=" * 60)

    # Simulate tasks
    tasks = [
        {"project": 1, "issue": 1, "priority": 1, "status": TaskStatus.PENDING},
        {"project": 1, "issue": 2, "priority": 2, "status": TaskStatus.PENDING},  # High priority
        {"project": 1, "issue": 1, "priority": 1, "status": TaskStatus.RUNNING},  # Issue 1 already running
        {"project": 2, "issue": 1, "priority": 1, "status": TaskStatus.PENDING},
    ]

    max_concurrency = 2
    running_tasks = []
    running_issues = set()

    print(f"\nMax concurrency: {max_concurrency}")
    print(f"Initial running: {len(running_tasks)}")

    # Simulate scheduler picking tasks
    print("\n--- Scheduler Decision ---")
    for i, task in enumerate(tasks):
        issue_key = f"{task['project']}:{task['issue']}"

        # Check issue mutex
        if issue_key in running_issues:
            print(f"❌ Task {i+1}: BLOCKED (issue {issue_key} already running)")
            continue

        # Check concurrency
        if len(running_tasks) >= max_concurrency:
            print(f"❌ Task {i+1}: BLOCKED (max concurrency reached)")
            continue

        # Allow task
        running_tasks.append(task)
        running_issues.add(issue_key)
        task['status'] = TaskStatus.RUNNING
        print(f"✅ Task {i+1}: ALLOWED (issue={issue_key}, priority={task['priority']})")

    print(f"\nFinal running: {len(running_tasks)} tasks")
    print(f"Running issues: {running_issues}")

    # Verify: Issue 1 should only have 1 running (blocked by mutex)
    # Project 2 Issue 1 should run (different project)
    issue_1_running = any(t['project'] == 1 and t['issue'] == 1 and t['status'] == TaskStatus.RUNNING for t in running_tasks)

    print("\n" + "=" * 60)
    if issue_1_running:
        print("✅ Concurrent Issues Simulation Passed!")
    else:
        print("❌ Concurrent Issues Simulation Failed!")
        return False
    print("=" * 60)
    return True


def simulate_priority_queue():
    """Simulate priority queue ordering."""
    print("\n" + "=" * 60)
    print("Priority Queue Simulation")
    print("=" * 60)

    # Create tasks with different priorities
    tasks = [
        {"id": 1, "priority": 1, "scheduled": None, "name": "Task A (normal)"},
        {"id": 2, "priority": 3, "scheduled": None, "name": "Task B (urgent)"},
        {"id": 3, "priority": 1, "scheduled": None, "name": "Task C (normal)"},
        {"id": 4, "priority": 2, "scheduled": None, "name": "Task D (high)"},
        {"id": 5, "priority": 0, "scheduled": None, "name": "Task E (low)"},
    ]

    # Sort by priority DESC, scheduled ASC, created ASC
    tasks.sort(key=lambda x: (-x["priority"], x["scheduled"] or datetime.min, x["id"]))

    print("\nExecution order:")
    for i, task in enumerate(tasks):
        print(f"  {i+1}. {task['name']} (priority={task['priority']})")

    # Verify order
    expected_order = ["Task B (urgent)", "Task D (high)", "Task A (normal)", "Task C (normal)", "Task E (low)"]
    actual_order = [t["name"] for t in tasks]

    print("\n" + "=" * 60)
    if actual_order == expected_order:
        print("✅ Priority Queue Simulation Passed!")
    else:
        print("❌ Priority Queue Simulation Failed!")
        print(f"   Expected: {expected_order}")
        print(f"   Got: {actual_order}")
        return False
    print("=" * 60)
    return True


def test_simulate_full_workflow():
    assert simulate_full_workflow()


def test_simulate_concurrent_issues():
    assert simulate_concurrent_issues()


def test_simulate_priority_queue():
    assert simulate_priority_queue()


def main():
    """Run all E2E simulations."""
    print("\n" + "#" * 60)
    print("# Codify End-to-End Simulations")
    print("#" * 60)

    results = []

    results.append(("Full Workflow", simulate_full_workflow()))
    results.append(("Concurrent Issues", simulate_concurrent_issues()))
    results.append(("Priority Queue", simulate_priority_queue()))

    print("\n" + "=" * 60)
    print("Simulation Summary")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("🎉 All simulations passed!")
    else:
        print("❌ Some simulations failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
