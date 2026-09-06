"""Behavioral tests for the unified Git delivery finalization (W1).

Drives the real repository-helpers.sh functions (pin -> collect -> publish ->
metadata) against a local bare remote, mirroring the conventions of
test_worker_repository_bootstrap.py: the production /workspace path is
textually replaced so the tests run without root, and codify_run_shell /
codify_chown are stubbed to the current process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HELPERS_SCRIPT = REPO_ROOT / "deploy" / "worker-entrypoint" / "repository-helpers.sh"
GIT_DELIVERY_SH = REPO_ROOT / "deploy" / "worker-entrypoint" / "git-delivery.sh"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _create_remote_with_work_branch(root: Path) -> tuple[Path, str]:
    """Bare remote whose default branch already has an issue work branch."""
    source = root / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.name", "Codify Test")
    _git(source, "config", "user.email", "codify-test@example.com")
    for index in range(3):
        (source / "history.txt").write_text(f"commit {index}\n")
        _git(source, "add", "history.txt")
        _git(source, "commit", "-qm", f"main {index}")

    branch_name = "codify/issue-42"
    _git(source, "checkout", "-q", "-b", branch_name)
    (source / "issue-branch.txt").write_text("previous task work\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "previous task work")
    previous = _git(source, "rev-parse", "HEAD")
    _git(source, "checkout", "-q", "main")

    remote = root / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(source), str(remote)],
        text=True,
        capture_output=True,
        check=True,
    )
    return remote, branch_name, previous


def _clone_workspace(root: Path, remote: Path, branch_name: str) -> Path:
    """Clone the work branch exactly as repository preparation leaves it."""
    workspace = root / "workspace"
    _git(root, "clone", "-q", str(remote), str(workspace))
    _git(workspace, "checkout", "-q", "-b", branch_name, f"origin/{branch_name}")
    _git(workspace, "config", "user.name", "Harness")
    _git(workspace, "config", "user.email", "harness@example.com")
    return workspace


def _run_delivery_scenario(
    root: Path,
    *,
    remote: Path,
    branch_name: str,
    workspace: Path,
    previous: str,
    scenario: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    base_sha = _git(remote, "rev-parse", "refs/heads/main")

    # Production uses the fixed /workspace mount; replace the bounded path so
    # the real module runs without root or host mutation.
    rendered_script = root / "delivery-under-test.sh"
    rendered_script.write_text(
        (
            HELPERS_SCRIPT.read_text() + "\n" + GIT_DELIVERY_SH.read_text()
        ).replace("/workspace", str(workspace))
    )

    env = {
        **os.environ,
        "HOME": str(root / "home"),
        "PATH": os.environ["PATH"],
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_RUNTIME_DIR": str(runtime_dir),
        "GIT_REPO_URL": remote.as_uri(),
        "BRANCH_NAME": branch_name,
        "BASE_BRANCH": "main",
        "REPO_REMOTE_WORK_SHA": previous,
        "REPO_REMOTE_BASE_SHA": base_sha,
        "TASK_ID": "42",
        "CODIFY_ATTEMPT_ID": "task-42-attempt-1",
        "TASK_MODE": "execute",
        "REQUIRE_CHANGES": "true",
        "USER_PROMPT": "delivery test",
        "GITLAB_TOKEN": "glpat-test",
    }
    if env_overrides:
        env.update(env_overrides)
    (root / "home").mkdir(exist_ok=True)

    harness = f"""
set -e
codify_run_shell() {{
    bash -c "$1"
}}
codify_chown() {{
    :
}}
export CODIFY_RUNTIME_DIR BRANCH_NAME BASE_BRANCH GIT_REPO_URL TASK_ID CODIFY_ATTEMPT_ID
export REPO_REMOTE_WORK_SHA REPO_REMOTE_BASE_SHA TASK_MODE REQUIRE_CHANGES USER_PROMPT
source "$1"
cd {workspace}
{scenario}
"""
    return subprocess.run(
        ["bash", "-c", harness, "delivery-test", str(rendered_script)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _snapshot(root: Path) -> dict:
    return json.loads(
        (root / "runtime" / "git-delivery.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def delivery_env(tmp_path: Path):
    """(remote, branch_name, previous_sha, workspace) with a fresh work clone."""
    remote, branch_name, previous = _create_remote_with_work_branch(tmp_path)
    workspace = _clone_workspace(tmp_path, remote, branch_name)
    return {
        "root": tmp_path,
        "remote": remote,
        "branch": branch_name,
        "previous": previous,
        "workspace": workspace,
    }


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_harness_commits_pushed_with_full_stats(delivery_env: dict):
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    scenario = """
repo_pin_delivery_start
printf 'a\\n' > h1.txt
git add h1.txt && git commit -qm "harness commit one"
printf 'b\\n' > h2.txt && git add h2.txt && git commit -qm "harness commit two"
H=$(git rev-parse HEAD)
repo_delivery_collect || exit 9
repo_delivery_has_content || exit 9
repo_delivery_publish || exit 8
repo_delivery_write_metadata || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = _snapshot(root)
    gd = snapshot["git_delivery"]
    assert [c["subject"] for c in gd["commits"]] == [
        "harness commit one",
        "harness commit two",
    ]
    assert gd["recovered_commits"] == []
    assert gd["diff"]["additions"] == 2
    assert gd["push"]["status"] == "pushed"
    assert gd["push"]["remote_sha"] == gd["head_sha"]
    assert snapshot["commit_sha"] == gd["head_sha"]
    # Metadata projection agrees with the snapshot.
    metadata = json.loads(
        (root / "runtime" / "task-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["commit_sha"] == gd["head_sha"]
    assert metadata["git_delivery"] == gd
    # Remote really contains the head.
    assert _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}") == gd["head_sha"]
    # The unconfirmed marker was cleared.
    assert subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=workspace,
        text=True,
        capture_output=True,
    ).returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_harness_pushed_a_then_committed_b_is_pushed(delivery_env: dict):
    """The old-lease bug: harness pushed A itself; the worker must still push B."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness A"
git push origin HEAD:refs/heads/%BRANCH%
printf 'y\\n' > a.txt
git add a.txt && git commit -qm "harness B"
H=$(git rev-parse HEAD)
A=$(git rev-parse HEAD~1)
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    scenario = scenario.replace("%BRANCH%", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert [c["subject"] for c in gd["commits"]] == ["harness A", "harness B"]
    assert gd["push"]["status"] == "pushed"
    remote_tip = _git(
        delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}"
    )
    assert remote_tip == gd["head_sha"]
    assert gd["start_sha"] != gd["head_sha"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_harness_pushed_everything_is_confirmed_without_extra_commit(delivery_env: dict):
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness self-pushed"
git push origin HEAD:refs/heads/%BRANCH%
H=$(git rev-parse HEAD)
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
test "$(git rev-parse HEAD)" = "$H"
"""
    scenario = scenario.replace("%BRANCH%", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert [c["subject"] for c in gd["commits"]] == ["harness self-pushed"]
    assert gd["push"]["status"] == "already_present"
    assert gd["head_sha"] == gd["push"]["remote_sha"]
    # Exactly one commit exists beyond the previous task head.
    assert _git(workspace, "rev-list", "--count", f"{delivery_env['previous']}..HEAD") == "1"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_worker_commit_covers_remaining_changes_after_harness_commit(delivery_env: dict):
    """Harness commits + leftover working tree changes -> worker commit, net diff covers all."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'one\\n' > h.txt
git add h.txt && git commit -qm "harness committed part"
printf 'two\\n' > leftover.txt
git add leftover.txt && git commit -qm "worker finishes"
H=$(git rev-parse HEAD)
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert len(gd["commits"]) == 2
    assert set(gd["diff"]["new_files"]) == {"h.txt", "leftover.txt"}
    assert gd["push"]["status"] == "pushed"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_recovered_commits_are_separate_and_pushed(delivery_env: dict):
    """A local commit from an earlier run sits between R0 and S (workspace reuse)."""
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    # Simulate the earlier run: unpushed local commit already on the branch.
    (workspace / "legacy.txt").write_text("older work\n")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-qm", "previous unpushed commit")
    scenario = """
repo_pin_delivery_start
printf 'new\\n' > fresh.txt
git add fresh.txt && git commit -qm "current task commit"
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert [c["subject"] for c in gd["commits"]] == ["current task commit"]
    assert [c["subject"] for c in gd["recovered_commits"]] == [
        "previous unpushed commit"
    ]
    assert gd["push"]["status"] == "pushed"
    # Net diff belongs to this task only; recovered work never double counts.
    assert gd["diff"]["additions"] == 1
    assert gd["diff"]["new_files"] == ["fresh.txt"]
    remote_tip = _git(
        delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}"
    )
    assert remote_tip == gd["head_sha"]
    # The recovered commit is really on the remote now.
    recovered = gd["recovered_commits"][0]["sha"]
    assert _git(
        delivery_env["remote"], "merge-base", "--is-ancestor", recovered, remote_tip
    ) is not None


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_recovered_only_delivery_confirms_without_new_commits(delivery_env: dict):
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    (workspace / "legacy.txt").write_text("older work\n")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-qm", "previous unpushed commit")
    scenario = """
repo_pin_delivery_start
repo_delivery_collect || exit 9
repo_delivery_has_content || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["commits"] == []
    assert len(gd["recovered_commits"]) == 1
    assert gd["push"]["status"] == "pushed"
    # Projection: commit_sha is the confirmed endpoint even without new commits.
    assert _snapshot(root)["commit_sha"] == gd["head_sha"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_unconfirmed_marker_confirms_existing_delivery(delivery_env: dict):
    """Push ACK was lost earlier; the marker commit is on the remote already."""
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    marker = delivery_env["previous"]
    _git(workspace, "config", "codify.unpublishedPushSha", marker)
    scenario = """
repo_pin_delivery_start
repo_delivery_collect || exit 9
repo_delivery_has_content || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=marker,
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["commits"] == []
    assert [c["sha"] for c in gd["recovered_commits"]] == [marker]
    assert gd["push"]["status"] == "already_present"
    assert subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=workspace,
        text=True,
        capture_output=True,
    ).returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_only_published_history_has_no_delivery_content(delivery_env: dict):
    """Only previously published history: empty lists, no push, not_needed."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
repo_delivery_collect || exit 9
if repo_delivery_has_content; then echo "unexpected content"; exit 9; fi
repo_delivery_record "not_needed" || exit 9
repo_delivery_write_metadata || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["commits"] == []
    assert gd["recovered_commits"] == []
    assert gd["push"]["status"] == "not_needed"
    assert _snapshot(root)["commit_sha"] is None


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_remote_ahead_with_our_head_is_confirmed_without_absorbing(delivery_env: dict):
    """Remote already contains H plus later commits; nothing is overwritten."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
H=$(git rev-parse HEAD)
git push origin HEAD:refs/heads/%BRANCH%
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
test "$(git rev-parse HEAD)" = "$H"
"""
    scenario = scenario.replace("%BRANCH%", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "already_present"
    # Remote tip stays exactly the pushed head (nothing extra, nothing lost).
    assert (
        _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}")
        == gd["head_sha"]
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_diverged_remote_fails_and_preserves_remote(delivery_env: dict):
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
repo_delivery_collect || exit 9
if repo_delivery_publish; then echo "expected refusal"; exit 8; fi
"""
    # A concurrent writer replaces the remote branch with unrelated history.
    other = root / "concurrent"
    subprocess.run(
        ["git", "clone", "-q", delivery_env["remote"].as_uri(), str(other)],
        text=True,
        capture_output=True,
        check=True,
    )
    _git(other, "checkout", "-q", "-b", delivery_env["branch"])
    (other / "evil.txt").write_text("evil\n")
    _git(other, "add", "-A")
    _git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "concurrent work")
    # Hostile concurrent overwrite: replace the remote branch with unrelated history.
    _git(other, "push", "-q", "--force", "origin", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "failed"
    assert gd["push"]["error"]["code"] == "remote_diverged"
    # Local facts preserved; remote untouched by us.
    assert len(gd["commits"]) == 1
    remote_tip = _git(
        delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}"
    )
    assert remote_tip != gd["head_sha"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_remote_rewind_is_refused(delivery_env: dict):
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
git push origin HEAD:refs/heads/%BRANCH%
# Human rewinds the remote behind the task-start tip.
git push origin "$REPO_REMOTE_BASE_SHA":refs/heads/%BRANCH% --force
repo_delivery_collect || exit 9
if repo_delivery_publish; then echo "expected refusal"; exit 8; fi
"""
    scenario = scenario.replace("%BRANCH%", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "failed"
    assert gd["push"]["error"]["code"] == "remote_rewound"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_remote_branch_deletion_is_refused(delivery_env: dict):
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
git push origin :refs/heads/%BRANCH%
repo_delivery_collect || exit 9
if repo_delivery_publish; then echo "expected refusal"; exit 8; fi
"""
    scenario = scenario.replace("%BRANCH%", delivery_env["branch"])
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "failed"
    assert gd["push"]["error"]["code"] == "remote_deleted"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_push_nonzero_with_remote_already_containing_head_is_confirmed(
    delivery_env: dict,
):
    """Push returns non-zero but the server wrote the ref: bounded recheck confirms."""
    root = delivery_env["root"]
    # Wrap git so the first push succeeds but reports failure (see
    # test_worker_repository_bootstrap conventions).
    wrapper_dir = root / "git-wrapper"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "push" ]; then\n'
        '    REAL_GIT="$REAL_GIT" "$REAL_GIT" "$@"\n'
        "    result=$?\n"
        '    [ "$result" -eq 0 ] || exit "$result"\n'
        "    exit 23\n"
        "fi\n"
        'exec "$REAL_GIT" "$@"\n'
    )
    wrapper.chmod(0o755)
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
H=$(git rev-parse HEAD)
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
        env_overrides={
            "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
            "REAL_GIT": shutil.which("git") or "git",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "already_present", gd["push"]
    assert (
        _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}")
        == gd["head_sha"]
    )
    # Confirmation cleared the uncertain-push marker.
    assert subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=delivery_env["workspace"],
        text=True,
        capture_output=True,
    ).returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_push_rejected_keeps_local_facts_and_fails(delivery_env: dict):
    """Server-side rejection (simulated by a wrapper) fails without fake SHA."""
    root = delivery_env["root"]
    wrapper_dir = root / "git-wrapper"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "push" ]; then\n'
        '    echo "rejected by policy" >&2\n'
        "    exit 1\n"
        "fi\n"
        'exec "$REAL_GIT" "$@"\n'
    )
    wrapper.chmod(0o755)
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
repo_delivery_collect || exit 9
if repo_delivery_publish; then echo "expected failure"; exit 8; fi
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
        env_overrides={
            "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
            "REAL_GIT": shutil.which("git") or "git",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "failed"
    assert gd["push"]["error"]["code"] == "push_failed"
    # Unconfirmed: no top-level commit projection.
    assert _snapshot(root)["commit_sha"] is None
    # Local facts preserved, remote unchanged.
    assert len(gd["commits"]) == 1
    assert (
        _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}")
        == delivery_env["previous"]
    )
    # The uncertain-push marker stays for the next run to reconcile.
    marker = subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=delivery_env["workspace"],
        text=True,
        capture_output=True,
    )
    assert marker.stdout.strip() == gd["head_sha"]


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_rewritten_start_history_stops_delivery(delivery_env: dict):
    """The harness rewrote the pinned start: no unattributable publishing."""
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    base = _git(delivery_env["remote"], "rev-parse", "refs/heads/main")
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
git reset --hard %BASE%
repo_delivery_collect || exit 9
"""
    scenario = scenario.replace("%BASE%", base)
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Collect produced a diagnostic error and left commits uncollected.
    snapshot = _snapshot(root)
    gd = snapshot["git_delivery"]
    assert gd["commits"] is None
    assert snapshot["commit_sha"] is None
    # The hard attribution error is persisted where main.sh gates on it, so a
    # rewritten start can never fall through to a false "no changes" success.
    assert snapshot["error"]["code"] == "history_rewritten"
    gate = subprocess.run(
        ["jq", "-r",
         '(.error.code // "") as $c | if $c != "" and .git_delivery.commits == null then $c else "" end',
         str(root / "runtime" / "git-delivery.json")],
        text=True, capture_output=True, check=True,
    )
    assert gate.stdout.strip() == "history_rewritten"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_detached_head_collect_fails_branch_changed(delivery_env: dict):
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
git checkout -q --detach
repo_delivery_collect || exit 9
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "not_attempted"
    assert gd["commits"] is None
    assert gd["diff"] is None
    assert _snapshot(root)["error"]["code"] == "branch_changed"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_weird_filenames_and_binary_are_collected_without_splitting(delivery_env: dict):
    """Commas/spaces/tabs/quotes in names plus binary files: lists stay intact."""
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > "we,ird name.txt"
printf 'x\\n' > "tab	separated.txt"
printf 'x\\n' > 'quo"te.txt'
printf '\\x00\\x01\\x02' > blob.bin
git add -A && git commit -qm "odd files"
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    new_files = set(gd["diff"]["new_files"])
    assert {"we,ird name.txt", "tab\tseparated.txt", 'quo"te.txt', "blob.bin"} == new_files
    assert gd["diff"]["additions"] == 3  # binary contributes no line counts
    assert gd["push"]["status"] == "pushed"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_net_zero_diff_still_delivers_commits(delivery_env: dict):
    """Commits with a net-zero diff (modify then revert) remain a delivery."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'change\\n' >> issue-branch.txt
git add -A && git commit -qm "harness change"
git revert --no-edit HEAD
repo_delivery_collect || exit 9
repo_delivery_has_content || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert len(gd["commits"]) == 2
    assert gd["diff"]["additions"] == 0
    assert gd["diff"]["deletions"] == 0
    assert gd["push"]["status"] == "pushed"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_failure_exit_collector_preserves_facts_without_push(delivery_env: dict):
    """The EXIT-path collector records facts and never touches the remote."""
    root = delivery_env["root"]
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit before crash"
repo_delivery_collect_facts_on_exit 1 || exit 9
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert [c["subject"] for c in gd["commits"]] == ["harness commit before crash"]
    assert gd["push"]["status"] == "not_attempted"
    assert _snapshot(root)["commit_sha"] is None
    # Remote untouched.
    assert (
        _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}")
        == delivery_env["previous"]
    )
    # Metadata was persisted too (backend stores worker_metadata from it).
    metadata = json.loads(
        (root / "runtime" / "task-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["git_delivery"]["push"]["status"] == "not_attempted"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_new_branch_is_created_when_remote_never_had_one(tmp_path: Path):
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.name", "Codify Test")
    _git(source, "config", "user.email", "codify-test@example.com")
    (source / "f.txt").write_text("base\n")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "base")
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(source), str(remote)],
        text=True,
        capture_output=True,
        check=True,
    )
    branch = "codify/issue-43"
    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", str(remote), str(workspace))
    # repository.sh would create the branch from origin/main.
    _git(workspace, "checkout", "-q", "-b", branch, "origin/main")
    _git(workspace, "config", "user.name", "Harness")
    _git(workspace, "config", "user.email", "harness@example.com")
    root = tmp_path
    scenario = """
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=remote,
        branch_name=branch,
        workspace=workspace,
        previous="",  # remote work branch never existed
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["start_remote_sha"] is None
    assert gd["push"]["status"] == "pushed"
    assert (
        _git(remote, "rev-parse", f"refs/heads/{branch}") == gd["head_sha"]
    )


# ---------------------------------------------------------------------------
# Canonical finalizer integration: worker.finalization/delivery events must be
# built from the same delivery snapshot that main.sh persisted.
# ---------------------------------------------------------------------------


def _run_finalize_scenario(tmp_path: Path, scenario: str) -> subprocess.CompletedProcess[str]:
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "ENTRYPOINT_LIB_DIR": str(REPO_ROOT / "deploy/worker-entrypoint"),
        "CODIFY_ORCHESTRATION_DIR": str(REPO_ROOT / "deploy"),
        "CODIFY_RUNTIME_DIR": str(runtime),
        "TASK_ID": "42",
        "CODIFY_ATTEMPT_ID": "task-42-attempt-1",
        "CODIFY_HARNESS_KEY": "claude",
        "CODIFY_ADAPTER_VERSION": "1.0.0",
        "CODIFY_CLI_VERSION": "2.1.0",
        "GIT_DELIVERY_SNAPSHOT_FILE": str(runtime / "git-delivery.json"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    harness = f"""
set -e
codify_chown() {{
    :
}}
export CODIFY_RUNTIME_DIR TASK_ID CODIFY_ATTEMPT_ID CODIFY_HARNESS_KEY
export CODIFY_ADAPTER_VERSION CODIFY_CLI_VERSION GIT_DELIVERY_SNAPSHOT_FILE
source "{REPO_ROOT / "deploy/worker-entrypoint/harness/common.sh"}"
{scenario}
"""
    return subprocess.run(
        ["bash", "-c", harness], env=env, text=True, capture_output=True, check=False
    )


def _read_events(runtime: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (runtime / "event.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_finalizer_carries_git_delivery_snapshot_into_events(tmp_path: Path):
    head = "a" * 40
    snapshot = {
        "commit_sha": head,
        "commit_message": "harness commit\n\nbody",
        "diff": {"additions": 7, "deletions": 3, "total": 10},
        "git_delivery": {
            "schema": "codify.git-delivery.v1",
            "attempt_id": "task-42-attempt-1",
            "branch": "codify/issue-42",
            "start_sha": "b" * 40,
            "start_remote_sha": "c" * 40,
            "head_sha": head,
            "commits": [{"sha": head, "subject": "harness commit"}],
            "recovered_commits": [],
            "diff": {"additions": 7, "deletions": 3, "total": 10, "new_files": [], "modified_files": [], "deleted_files": []},
            "push": {"status": "pushed", "remote_sha": head, "error": None},
        },
    }
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime" / "git-delivery.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    scenario = """
codify_emit_event "run.started" '{}'
codify_emit_event "harness.completed" '{}'
codify_harness_mark_delivery_started
codify_harness_finalize_attempt 0
"""
    result = _run_finalize_scenario(tmp_path, scenario)
    assert result.returncode == 0, result.stdout + result.stderr

    events = _read_events(tmp_path / "runtime")
    types = [event["type"] for event in events]
    assert types == [
        "run.started",
        "harness.completed",
        "delivery.started",
        "delivery.completed",
        "worker.finalization",
        "run.completed",
    ]
    delivery = next(event for event in events if event["type"] == "delivery.completed")
    assert delivery["payload"]["commit_sha"] == head
    finalization = next(event for event in events if event["type"] == "worker.finalization")
    payload = finalization["payload"]
    assert payload["commit_sha"] == head
    assert payload["commit_message"].startswith("harness commit")
    assert payload["diff"]["additions"] == 7
    assert payload["git_delivery"]["push"]["status"] == "pushed"
    assert payload["git_delivery"]["commits"][0]["sha"] == head


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_finalizer_reports_delivery_failure_reason_in_run_failed(tmp_path: Path):
    snapshot = {
        "commit_sha": None,
        "commit_message": None,
        "diff": None,
        "git_delivery": {
            "schema": "codify.git-delivery.v1",
            "attempt_id": "task-42-attempt-1",
            "branch": "codify/issue-42",
            "start_sha": "b" * 40,
            "start_remote_sha": "c" * 40,
            "head_sha": "a" * 40,
            "commits": [{"sha": "a" * 40, "subject": "harness commit"}],
            "recovered_commits": [],
            "diff": None,
            "push": {
                "status": "failed",
                "remote_sha": None,
                "error": {
                    "code": "remote_diverged",
                    "message": "The remote task branch and the local head have diverged",
                },
            },
        },
    }
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime" / "git-delivery.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    scenario = """
codify_emit_event "run.started" '{}'
codify_emit_event "harness.completed" '{}'
codify_harness_mark_delivery_started
codify_harness_finalize_attempt 1
"""
    result = _run_finalize_scenario(tmp_path, scenario)
    assert result.returncode == 0, result.stdout + result.stderr

    events = _read_events(tmp_path / "runtime")
    failed = next(event for event in events if event["type"] == "delivery.failed")
    assert failed["payload"]["commit_sha"] is None
    assert failed["payload"]["failure"]["code"] == "remote_diverged"
    run_failed = next(event for event in events if event["type"] == "run.failed")
    message = run_failed["payload"]["failure"]["message"]
    assert "have diverged" in message


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_finalizer_legacy_fallback_without_snapshot(tmp_path: Path):
    """Attempts that never reached Git delivery keep the legacy payload shape."""
    scenario = """
codify_emit_event "run.started" '{}'
codify_emit_event "harness.completed" '{}'
CODIFY_DELIVERY_STARTED=1
codify_harness_finalize_attempt 0
"""
    result = _run_finalize_scenario(tmp_path, scenario)
    assert result.returncode == 0, result.stdout + result.stderr
    events = _read_events(tmp_path / "runtime")
    finalization = next(event for event in events if event["type"] == "worker.finalization")
    assert "git_delivery" not in finalization["payload"]
    assert finalization["payload"]["commit_sha"] is None
    assert finalization["payload"]["diff"] == {"additions": 0, "deletions": 0, "total": 0}


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_finalizer_runs_failure_fact_preservation_before_events(tmp_path: Path):
    """On failed exits the finalizer preserves facts before emitting events."""
    marker = tmp_path / "collected.marker"
    scenario = f"""
codify_chown() {{
    :
}}
repo_delivery_collect_facts_on_exit() {{
    touch "{marker}"
    return 0
}}
codify_emit_event "run.started" '{{}}'
codify_emit_event "harness.failed" '{{"failure":{{"kind":"engine_error","message":"boom"}}}}'
codify_harness_finalize_attempt 1
"""
    result = _run_finalize_scenario(tmp_path, scenario)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists()
    events = _read_events(tmp_path / "runtime")
    types = [event["type"] for event in events]
    assert "worker.finalization" in types
    assert types[-1] == "run.failed"


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_rewritten_start_never_declares_false_success_even_in_freeform(delivery_env: dict):
    """Replicates main.sh's delivery tail: a rewritten pinned start must fail
    with the recorded reason in every task mode (require_changes=false here)."""
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    base = _git(delivery_env["remote"], "rev-parse", "refs/heads/main")
    scenario = """
repo_pin_delivery_start
printf 'x\n' > a.txt
git add a.txt && git commit -qm "harness commit"
git reset --hard %BASE%
repo_delivery_collect || exit 9
# ---- main.sh gate (verbatim) ----
DELIVERY_COLLECT_ERROR=$(jq -r \
    '(.error.code // "") as $c | if $c != "" and .git_delivery.commits == null then $c else "" end' \
    "${GIT_DELIVERY_SNAPSHOT_FILE}" 2>/dev/null || true)
if [ -n "${DELIVERY_COLLECT_ERROR}" ]; then
    DELIVERY_COLLECT_MESSAGE=$(jq -r '.error.message // "Delivery facts could not be collected"' "${GIT_DELIVERY_SNAPSHOT_FILE}")
    echo "ERROR: ${DELIVERY_COLLECT_MESSAGE}"
    repo_delivery_record "failed" "" "${DELIVERY_COLLECT_ERROR}" "${DELIVERY_COLLECT_MESSAGE}" || true
    repo_delivery_write_metadata || true
    exit 1
fi
repo_delivery_record "not_needed" || true
echo "false success path reached"
exit 0
"""
    scenario = scenario.replace("%BASE%", base)
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
        env_overrides={"REQUIRE_CHANGES": "false", "TASK_MODE": "freeform"},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "false success path" not in result.stdout
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "failed"
    assert gd["push"]["error"]["code"] == "history_rewritten"
    metadata = json.loads(
        (root / "runtime" / "task-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["commit_sha"] is None


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_harness_repointing_origin_never_diverts_delivery(delivery_env: dict):
    """Remote observation, fetch and push bind the FROZEN repository URL.

    The Harness repoints `origin` at an evil clone that already contains H;
    delivery must still reconcile against the task repository.
    """
    root = delivery_env["root"]
    workspace = delivery_env["workspace"]
    # Evil clone of the real remote: it will receive the harness push.
    evil = root / "evil.git"
    subprocess.run(
        ["git", "clone", "--bare", "-q", str(delivery_env["remote"]), str(evil)],
        text=True,
        capture_output=True,
        check=True,
    )
    scenario = f"""
repo_pin_delivery_start
printf 'x\\n' > a.txt
git add a.txt && git commit -qm "harness commit"
H=$(git rev-parse HEAD)
# Harness repoints origin at the evil clone and pushes H there only.
git remote set-url origin "{evil.as_uri()}"
git push -q origin HEAD:refs/heads/{delivery_env["branch"]}
test "$(git ls-remote origin refs/heads/{delivery_env["branch"]} | cut -f1)" = "$H"
repo_delivery_collect || exit 9
repo_delivery_publish || exit 8
"""
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=workspace,
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gd = _snapshot(root)["git_delivery"]
    assert gd["push"]["status"] == "pushed"
    # The REAL task repository received H (no false already_present against the
    # evil clone); the evil clone only has the harness push.
    assert (
        _git(delivery_env["remote"], "rev-parse", f"refs/heads/{delivery_env['branch']}")
        == gd["head_sha"]
    )
    assert _git(evil, "rev-parse", f"refs/heads/{delivery_env['branch']}") == gd["head_sha"]
    # Marker cleared only after the confirmed record.
    marker = subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=workspace,
        text=True,
        capture_output=True,
    )
    assert marker.returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="helpers require jq")
def test_confirmed_record_failure_fails_run_and_keeps_marker(delivery_env: dict):
    """Snapshot write failure after a successful push must fail the run and
    retain the unconfirmed marker (remote already has H, snapshot must not
    claim otherwise, and the next run must be able to reconcile)."""
    root = delivery_env["root"]
    runtime_dir = root / "runtime"
    scenario = """
repo_pin_delivery_start
printf 'x\n' > a.txt
git add a.txt && git commit -qm "harness commit"
repo_delivery_collect || exit 9
# Make the snapshot location read-only so record_push cannot persist.
chmod 555 %RUNTIME%
if repo_delivery_publish; then echo "expected publish failure"; exit 8; fi
"""
    scenario = scenario.replace("%RUNTIME%", str(runtime_dir))
    result = _run_delivery_scenario(
        root,
        remote=delivery_env["remote"],
        branch_name=delivery_env["branch"],
        workspace=delivery_env["workspace"],
        previous=delivery_env["previous"],
        scenario=scenario,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = _snapshot(root)
    assert snapshot["git_delivery"]["push"]["status"] == "not_attempted"
    assert snapshot["commit_sha"] is None
    # The unconfirmed marker survives for the next run's reconciliation.
    marker = subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=delivery_env["workspace"],
        text=True,
        capture_output=True,
    )
    assert marker.stdout.strip() == snapshot["git_delivery"]["head_sha"]
