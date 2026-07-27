"""Behavioral tests for worker repository preparation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPOSITORY_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "worker-entrypoint"
    / "repository.sh"
)
REPOSITORY_HELPERS_SCRIPT = REPOSITORY_SCRIPT.with_name("repository-helpers.sh")
BOOTSTRAP_SCRIPT = REPOSITORY_SCRIPT.with_name("bootstrap.sh")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _create_remote_with_issue_branch(root: Path) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Codify Test")
    _git(source, "config", "user.email", "codify-test@example.com")

    for index in range(5):
        (source / "history.txt").write_text(f"commit {index}\n")
        _git(source, "add", "history.txt")
        _git(source, "commit", "-m", f"main {index}")

    branch_name = "codify/issue-123"
    _git(source, "checkout", "-b", branch_name)
    (source / "issue-branch.txt").write_text("existing remote issue branch\n")
    _git(source, "add", "issue-branch.txt")
    _git(source, "commit", "-m", "existing issue work")
    _git(source, "checkout", "main")

    remote = root / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(remote)],
        text=True,
        capture_output=True,
        check=True,
    )
    _git(remote, "config", "uploadpack.allowFilter", "true")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    return remote, branch_name


def _commit_to_remote_work_branch(
    root: Path,
    *,
    remote: Path,
    branch_name: str,
    checkout_name: str,
    filename: str,
    content: str,
) -> str:
    checkout = root / checkout_name
    subprocess.run(
        ["git", "clone", remote.as_uri(), str(checkout)],
        text=True,
        capture_output=True,
        check=True,
    )
    _git(checkout, "config", "user.name", "Human Contributor")
    _git(checkout, "config", "user.email", "human@example.com")
    _git(checkout, "checkout", branch_name)
    (checkout / filename).write_text(content)
    _git(checkout, "add", filename)
    _git(checkout, "commit", "-m", f"human update {filename}")
    _git(checkout, "push", "origin", branch_name)
    return _git(checkout, "rev-parse", "HEAD")


def _run_repository_script(
    root: Path,
    *,
    remote: Path,
    branch_name: str,
    workspace: Path,
    base_branch: str = "main",
    reject_filter: bool = False,
    push_succeeds_then_reports_failure: bool = False,
    post_source_command: str = "",
    clone_depth: int | None = 2,
    clone_filter: str | None = "blob:none",
) -> subprocess.CompletedProcess[str]:
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    home_dir = root / "home"
    home_dir.mkdir(exist_ok=True)

    # Production deliberately uses the fixed /workspace mount. Replacing that bounded path
    # lets this test exercise the real module without requiring root or mutating the host.
    rendered_script = root / "repository-under-test.sh"
    rendered_script.write_text(
        (
            REPOSITORY_HELPERS_SCRIPT.read_text()
            + "\n"
            + REPOSITORY_SCRIPT.read_text()
        ).replace("/workspace", str(workspace))
    )

    env = {
        **os.environ,
        "HOME": str(home_dir),
        "GIT_REPO_URL": remote.as_uri(),
        "BASE_BRANCH": base_branch,
        "BRANCH_NAME": branch_name,
        "USER_PROMPT": "test repository preparation",
        "CODIFY_GIT_CLONE_DEPTH": str(clone_depth) if clone_depth is not None else "",
        "CODIFY_GIT_CLONE_FILTER": clone_filter or "",
        "CODIFY_GIT_CONFIG": str(home_dir / ".gitconfig"),
        "REPOSITORY_PREPARATION_FILE": str(
            runtime_dir / "repository-preparation.json"
        ),
        "REPOSITORY_POST_SOURCE_COMMAND": post_source_command,
    }
    if reject_filter or push_succeeds_then_reports_failure:
        git_wrapper_dir = root / "git-wrapper"
        git_wrapper_dir.mkdir(exist_ok=True)
        git_wrapper = git_wrapper_dir / "git"
        git_wrapper.write_text(
            f"""#!/bin/sh
for argument in "$@"; do
    case "${{argument}}" in
        --filter=*)
            if [ "{str(reject_filter).lower()}" != "true" ]; then
                break
            fi
            echo "filtering is not supported by this test remote" >&2
            exit 23
            ;;
    esac
done
if [ "$1" = "push" ] && [ "{str(push_succeeds_then_reports_failure).lower()}" = "true" ]; then
    "${{REAL_GIT}}" "$@"
    result=$?
    [ "${{result}}" -eq 0 ] || exit "${{result}}"
    exit 23
fi
exec "${{REAL_GIT}}" "$@"
"""
        )
        git_wrapper.chmod(0o755)
        env["REAL_GIT"] = shutil.which("git") or "git"
        env["PATH"] = f"{git_wrapper_dir}:{env['PATH']}"
        # The production bootstrap always creates the bounded mount target before clone.
        workspace.mkdir(exist_ok=True)

    harness = """
set -e
codify_run_shell() {
    bash -c "$1"
}
codify_chown() {
    :
}
trap 'status=$?; if declare -F repo_finalize_preparation_on_exit >/dev/null 2>&1; then repo_finalize_preparation_on_exit "${status}" || true; fi' EXIT
source "$1"
if [ -n "${REPOSITORY_POST_SOURCE_COMMAND}" ]; then
    eval "${REPOSITORY_POST_SOURCE_COMMAND}"
fi
"""
    return subprocess.run(
        ["bash", "-c", harness, "repository-test", str(rendered_script)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_shallow_partial_clone_recovers_existing_issue_branch_and_writes_telemetry(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(workspace, "branch", "--show-current") == branch_name
    assert (workspace / "issue-branch.txt").read_text() == "existing remote issue branch\n"
    assert _git(workspace, "rev-parse", "--is-shallow-repository") == "true"
    assert _git(workspace, "config", "--get", "remote.origin.partialclonefilter") == "blob:none"

    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["status"] == "ready"
    assert telemetry["phase"] == "ready"
    assert telemetry["exit_code"] == 0
    assert telemetry["action"] == "clone"
    assert telemetry["workspace_reused"] is False
    assert telemetry["configured_depth"] == 2
    assert telemetry["configured_filter"] == "blob:none"
    assert telemetry["actual_shallow"] is True
    assert telemetry["effective_filter"] == "blob:none"
    assert telemetry["fallback"] is None
    assert telemetry["remote_work_branch"] is True
    assert telemetry["base_branch"] == "main"
    assert telemetry["work_branch"] == branch_name
    assert telemetry["elapsed_ms"] >= 0

    assert (
        "[repo] prepare workspace=new strategy=shallow depth=2 filter=blob:none"
        in result.stdout
    )
    base_sha = _git(remote, "rev-parse", "refs/heads/main")
    assert f"[repo] remote_refs base={base_sha} " in result.stdout
    assert "[repo] remote_refs base=ref:" not in result.stdout
    assert f"[repo] fetching existing work branch={branch_name}" in result.stdout
    assert "[repo] actual_state shallow=true effective_filter=blob:none" in result.stdout
    assert "[repo] ready action=clone" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_interrupted_shallow_clone_still_recovers_remote_issue_branch(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "2",
            "--single-branch",
            "--branch",
            "main",
            remote.as_uri(),
            str(workspace),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(workspace, "branch", "--show-current") == branch_name
    assert (workspace / "issue-branch.txt").is_file()
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["action"] == "fetch"
    assert telemetry["workspace_reused"] is True
    assert telemetry["remote_work_branch"] is True
    assert "[repo] prepare workspace=reused strategy=shallow" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_fast_forwards_a_human_remote_update(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    remote_sha = _commit_to_remote_work_branch(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        checkout_name="human-fast-forward",
        filename="human-update.txt",
        content="remote work\n",
    )
    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert (workspace / "human-update.txt").read_text() == "remote work\n"
    assert _git(workspace, "rev-parse", "HEAD") == remote_sha
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["action"] == "fetch"
    assert telemetry["work_branch_relation"] == "remote_ahead"
    assert telemetry["sync_action"] == "fast_forward"
    assert telemetry["remote_work_sha"] == remote_sha
    assert (
        f"[repo] sync work_branch={branch_name} relation=remote_ahead "
        "action=fast_forward dirty=false"
    ) in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_full_history_workspace_uses_the_same_safe_fast_forward(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        clone_depth=None,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    remote_sha = _commit_to_remote_work_branch(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        checkout_name="human-full-fast-forward",
        filename="human-full-update.txt",
        content="remote full-history work\n",
    )
    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        clone_depth=None,
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _git(workspace, "rev-parse", "HEAD") == remote_sha
    assert "[repo] fetch refs=base,work depth=full" in resumed.stdout
    assert "relation=remote_ahead action=fast_forward" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_preserves_an_unpushed_local_commit(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    (workspace / "local-only.txt").write_text("unpublished work\n")
    _git(workspace, "add", "local-only.txt")
    _git(workspace, "commit", "-m", "local unpublished work")
    local_sha = _git(workspace, "rev-parse", "HEAD")

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _git(workspace, "rev-parse", "HEAD") == local_sha
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["work_branch_relation"] == "local_ahead"
    assert telemetry["sync_action"] == "preserve_local"


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_clean_reused_workspace_pushes_a_preserved_local_commit(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    (workspace / "local-only.txt").write_text("unpublished work\n")
    _git(workspace, "add", "local-only.txt")
    _git(workspace, "commit", "-m", "local unpublished work")
    local_sha = _git(workspace, "rev-parse", "HEAD")
    assert _git(workspace, "status", "--porcelain") == ""

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        post_source_command=(
            "repo_has_unpublished_local_head && repo_push_work_branch_with_lease"
        ),
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _git(remote, "rev-parse", f"refs/heads/{branch_name}") == local_sha
    assert "relation=local_ahead action=preserve_local" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_push_nonzero_is_recovered_when_remote_matches_local_commit(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    (workspace / "ambiguous-push.txt").write_text("delivered before disconnect\n")
    _git(workspace, "add", "ambiguous-push.txt")
    _git(workspace, "commit", "-m", "ambiguous push")
    local_sha = _git(workspace, "rev-parse", "HEAD")

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        push_succeeds_then_reports_failure=True,
        post_source_command="repo_push_work_branch_with_lease",
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _git(remote, "rev-parse", f"refs/heads/{branch_name}") == local_sha
    assert "push_recovered result=remote_matches_local exit=23" in resumed.stdout
    marker = subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    assert marker.returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_retry_finalizes_a_previously_uncertain_push_when_remote_already_matches(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr
    local_sha = _git(workspace, "rev-parse", "HEAD")
    _git(workspace, "config", "codify.unpublishedPushSha", local_sha)

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        post_source_command=(
            "repo_has_unpublished_local_head && repo_push_work_branch_with_lease"
        ),
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "relation=same action=none" in resumed.stdout
    marker = subprocess.run(
        ["git", "config", "--get", "codify.unpublishedPushSha"],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    assert marker.returncode != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_accepts_remote_advancing_into_local_unpublished_history(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    previous_remote_sha = _git(remote, "rev-parse", f"refs/heads/{branch_name}")
    partially_published_sha = ""
    for index in range(2):
        filename = f"local-unpublished-{index}.txt"
        (workspace / filename).write_text(f"local unpublished {index}\n")
        _git(workspace, "add", filename)
        _git(workspace, "commit", "-m", f"local unpublished {index}")
        if index == 0:
            partially_published_sha = _git(workspace, "rev-parse", "HEAD")
    local_sha = _git(workspace, "rev-parse", "HEAD")

    # Transfer the first local commit without updating origin/<work-branch> in the
    # persistent workspace, then simulate a human advancing the real remote branch to it.
    transfer_ref = "refs/heads/codify-test-partial-publish"
    _git(workspace, "push", "origin", f"{partially_published_sha}:{transfer_ref}")
    _git(
        remote,
        "update-ref",
        f"refs/heads/{branch_name}",
        partially_published_sha,
        previous_remote_sha,
    )
    _git(remote, "update-ref", "-d", transfer_ref, partially_published_sha)

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert _git(workspace, "rev-parse", "HEAD") == local_sha
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["previous_remote_work_sha"] == previous_remote_sha
    assert telemetry["remote_work_sha"] == partially_published_sha
    assert telemetry["work_branch_relation"] == "local_ahead"
    assert telemetry["sync_action"] == "preserve_local"
    assert "relation=local_ahead action=preserve_local" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_rejects_diverged_human_and_local_commits(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    (workspace / "local-diverged.txt").write_text("local work\n")
    _git(workspace, "add", "local-diverged.txt")
    _git(workspace, "commit", "-m", "local divergent work")
    local_sha = _git(workspace, "rev-parse", "HEAD")
    remote_sha = _commit_to_remote_work_branch(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        checkout_name="human-diverged",
        filename="remote-diverged.txt",
        content="remote work\n",
    )

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode != 0
    assert _git(workspace, "rev-parse", "HEAD") == local_sha
    assert not (workspace / "remote-diverged.txt").exists()
    assert (
        f"[repo] error work_branch={branch_name} relation=diverged "
        f"local={local_sha} remote={remote_sha}"
    ) in resumed.stdout
    assert "refusing to merge or overwrite remote changes" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_rejects_a_human_remote_rewind(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    previous_remote_sha = _git(remote, "rev-parse", f"refs/heads/{branch_name}")
    rewound_remote_sha = _git(remote, "rev-parse", f"{previous_remote_sha}^")
    _git(
        remote,
        "update-ref",
        f"refs/heads/{branch_name}",
        rewound_remote_sha,
        previous_remote_sha,
    )

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode != 0
    assert _git(workspace, "rev-parse", "HEAD") == previous_remote_sha
    assert (
        f"[repo] error work_branch={branch_name} relation=remote_rewound "
        f"previous_remote={previous_remote_sha} current_remote={rewound_remote_sha}"
    ) in resumed.stdout
    assert "refusing to restore removed commits" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_workspace_rejects_a_human_remote_branch_deletion(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    previous_remote_sha = _git(remote, "rev-parse", f"refs/heads/{branch_name}")
    _git(remote, "update-ref", "-d", f"refs/heads/{branch_name}", previous_remote_sha)

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode != 0
    assert _git(workspace, "rev-parse", "HEAD") == previous_remote_sha
    assert (
        f"[repo] error work_branch={branch_name} relation=remote_deleted "
        f"previous_remote={previous_remote_sha}"
    ) in resumed.stdout
    assert "refusing to recreate it automatically" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_reused_dirty_workspace_rejects_a_remote_fast_forward(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    dirty_file = workspace / "unfinished-local-work.txt"
    dirty_file.write_text("keep local edits\n")
    _commit_to_remote_work_branch(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        checkout_name="human-dirty-fast-forward",
        filename="remote-while-dirty.txt",
        content="remote work\n",
    )

    resumed = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert resumed.returncode != 0
    assert dirty_file.read_text() == "keep local edits\n"
    assert not (workspace / "remote-while-dirty.txt").exists()
    assert (
        f"[repo] error work_branch={branch_name} relation=remote_ahead "
        "workspace=dirty"
    ) in resumed.stdout
    assert "refusing to overwrite local work" in resumed.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_exact_push_lease_accepts_unchanged_remote_and_rejects_concurrent_update(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    initial = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr

    prepared_sha = _git(remote, "rev-parse", f"refs/heads/{branch_name}")
    (workspace / "first-task-change.txt").write_text("first task change\n")
    _git(workspace, "add", "first-task-change.txt")
    _git(workspace, "commit", "-m", "first task change")
    first_local_sha = _git(workspace, "rev-parse", "HEAD")
    first_push = subprocess.run(
        [
            "git",
            "push",
            "-u",
            f"--force-with-lease=refs/heads/{branch_name}:{prepared_sha}",
            "origin",
            branch_name,
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first_push.returncode == 0, first_push.stdout + first_push.stderr
    assert _git(remote, "rev-parse", f"refs/heads/{branch_name}") == first_local_sha

    (workspace / "second-task-change.txt").write_text("second task change\n")
    _git(workspace, "add", "second-task-change.txt")
    _git(workspace, "commit", "-m", "second task change")
    human_sha = _commit_to_remote_work_branch(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        checkout_name="human-during-task",
        filename="human-during-task.txt",
        content="concurrent remote work\n",
    )
    concurrent_push = subprocess.run(
        [
            "git",
            "push",
            "-u",
            f"--force-with-lease=refs/heads/{branch_name}:{first_local_sha}",
            "origin",
            branch_name,
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )

    assert concurrent_push.returncode != 0
    assert _git(remote, "rev-parse", f"refs/heads/{branch_name}") == human_sha


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_partial_clone_failure_falls_back_without_losing_shallow_policy(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        reject_filter=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(workspace, "branch", "--show-current") == branch_name
    assert _git(workspace, "rev-parse", "--is-shallow-repository") == "true"
    assert (
        subprocess.run(
            ["git", "config", "--get", "remote.origin.partialclonefilter"],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 1
    )

    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["configured_depth"] == 2
    assert telemetry["configured_filter"] == "blob:none"
    assert telemetry["actual_shallow"] is True
    assert telemetry["effective_filter"] is None
    assert telemetry["fallback"] == "filter_disabled"
    assert "[repo] warning filter=blob:none clone_failed exit=23" in result.stdout
    assert "[repo] fallback retrying clone without object filter" in result.stdout
    assert "fallback=filter_disabled" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_non_git_nonempty_workspace_is_preserved_and_clone_is_refused(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "uncommitted-work.txt"
    marker.write_text("must survive\n")

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        reject_filter=True,
    )

    assert result.returncode != 0
    assert marker.read_text() == "must survive\n"
    assert not (workspace / ".git").exists()
    assert (
        "[repo] error workspace=nonempty git_metadata=missing; refusing clone"
        in result.stdout
    )
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["status"] == "failed"
    assert telemetry["phase"] == "clone"
    assert telemetry["exit_code"] == result.returncode


def test_runtime_archive_can_be_created_before_claude_outputs(
    tmp_path: Path,
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "console.log").write_text("repository failed\n")
    (runtime_dir / "repository-preparation.json").write_text(
        '{"status":"failed","phase":"clone"}\n'
    )
    bootstrap = BOOTSTRAP_SCRIPT.read_text()
    match = re.search(r"(?ms)^create_runtime_archive\(\) \{\n.*?^\}\n", bootstrap)
    assert match is not None

    harness = (
        "set -e\n"
        f"CODIFY_RUNTIME_DIR={runtime_dir!s}\n"
        "TASK_ID=77\n"
        "RUNTIME_ARCHIVE_CREATED=0\n"
        f"{match.group(0)}\n"
        "create_runtime_archive\n"
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    archive_path = runtime_dir / "task-77-runtime-archive.tar.gz"
    assert archive_path.is_file()
    with tarfile.open(archive_path, "r:gz") as archive:
        assert set(archive.getnames()) == {
            "console.log",
            "repository-preparation.json",
        }


def test_runtime_archive_fallback_removes_output_over_hard_limit(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "console.log").write_bytes(os.urandom(32 * 1024))
    bootstrap = BOOTSTRAP_SCRIPT.read_text()
    match = re.search(r"(?ms)^create_runtime_archive\(\) \{\n.*?^\}\n", bootstrap)
    assert match is not None
    bounded_function = match.group(0).replace(
        "local archive_max_bytes=$((640 * 1024 * 1024))",
        "local archive_max_bytes=1024",
    )

    harness = (
        "set -e\n"
        f"CODIFY_RUNTIME_DIR={runtime_dir!s}\n"
        "CODIFY_ARTIFACT_HELPER=\n"
        "TASK_ID=78\n"
        "RUNTIME_ARCHIVE_CREATED=0\n"
        f"{bounded_function}\n"
        "create_runtime_archive\n"
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    archive_path = runtime_dir / "task-78-runtime-archive.tar.gz"
    assert not archive_path.exists()
    assert not archive_path.with_suffix(".gz.part").exists()
    assert "exceeds the 640 MiB hard limit" in result.stdout


def test_runtime_archive_fallback_never_publishes_partial_tar_output(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "console.log").write_text("base\n", encoding="utf-8")
    bootstrap = BOOTSTRAP_SCRIPT.read_text()
    match = re.search(r"(?ms)^create_runtime_archive\(\) \{\n.*?^\}\n", bootstrap)
    assert match is not None

    harness = (
        "set -e\n"
        f"CODIFY_RUNTIME_DIR={runtime_dir!s}\n"
        "CODIFY_ARTIFACT_HELPER=\n"
        "TASK_ID=79\n"
        "RUNTIME_ARCHIVE_CREATED=0\n"
        "tar() { printf partial; return 2; }\n"
        f"{match.group(0)}\n"
        "create_runtime_archive\n"
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    archive_path = runtime_dir / "task-79-runtime-archive.tar.gz"
    assert not archive_path.exists()
    assert not archive_path.with_suffix(".gz.part").exists()
    assert "creation failed; archive omitted" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_server_ignored_filter_is_reported_as_ineffective_without_retry(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    _git(remote, "config", "--unset", "uploadpack.allowFilter")
    workspace = tmp_path / "workspace"

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "filtering not recognized by server, ignoring" in result.stdout
    assert (
        "[repo] warning filter=blob:none ignored_by_server; "
        "continuing with full objects"
    ) in result.stdout
    assert (
        subprocess.run(
            ["git", "config", "--get", "remote.origin.partialclonefilter"],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 1
    )

    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["configured_filter"] == "blob:none"
    assert telemetry["effective_filter"] is None
    assert telemetry["fallback"] == "filter_ignored"


@pytest.mark.skipif(shutil.which("jq") is None, reason="repository module requires jq")
def test_missing_base_branch_does_not_match_a_suffix_branch(
    tmp_path: Path,
):
    remote, branch_name = _create_remote_with_issue_branch(tmp_path)
    main_sha = _git(remote, "rev-parse", "refs/heads/main")
    _git(
        remote,
        "update-ref",
        "refs/heads/archive/missing-base",
        main_sha,
    )
    workspace = tmp_path / "workspace"

    result = _run_repository_script(
        tmp_path,
        remote=remote,
        branch_name=branch_name,
        workspace=workspace,
        base_branch="missing-base",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[repo] base_branch_fallback from=missing-base to=main" in result.stdout
    telemetry = json.loads(
        (tmp_path / "runtime" / "repository-preparation.json").read_text()
    )
    assert telemetry["base_branch"] == "main"
