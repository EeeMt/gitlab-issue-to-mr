"""Mock services server — GitLab API + Git HTTP backend + Anthropic API stub.

A single FastAPI app that replaces all external dependencies for integration testing.
Runs in a Docker container within the test compose network.
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock-services")

app = FastAPI(title="Mock Services")

# ---------------------------------------------------------------------------
# Call recording — every API call is logged for test assertions
# ---------------------------------------------------------------------------
_call_log: list[dict[str, Any]] = []
_call_log_lock = threading.Lock()


def record_call(service: str, method: str, path: str, body: Any = None, extra: dict | None = None):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": service,
        "method": method,
        "path": path,
        "body": body,
    }
    if extra:
        entry.update(extra)
    with _call_log_lock:
        _call_log.append(entry)
    logger.info(f"[{service}] {method} {path}")


@app.get("/mock/calls")
async def get_calls(service: str | None = None, method: str | None = None):
    """Retrieve recorded calls for test assertions."""
    with _call_log_lock:
        calls = list(_call_log)
    if service:
        calls = [c for c in calls if c["service"] == service]
    if method:
        calls = [c for c in calls if c["method"] == method]
    return calls


@app.delete("/mock/calls")
async def clear_calls():
    """Clear all recorded calls (use between tests)."""
    with _call_log_lock:
        _call_log.clear()
    return {"status": "cleared"}


@app.get("/mock/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Configurable mock behaviors — tests can change responses at runtime
# ---------------------------------------------------------------------------
_mock_config: dict[str, Any] = {
    "project_name": "test-project",
    "project_namespace": "test-group",
    "default_branch": "main",
    "mr_iid": 1,
    "claude_exit_code": 0,
    "claude_delay_seconds": 0,
    "claude_result": "Created hello.py with greeting function",
    "claude_file_changes": [
        {"path": "hello.py", "content": 'def hello():\n    return "Hello from Codify!"\n'}
    ],
}


@app.get("/mock/config")
async def get_mock_config():
    return _mock_config


@app.patch("/mock/config")
async def update_mock_config(request: Request):
    body = await request.json()
    _mock_config.update(body)
    return _mock_config


# ---------------------------------------------------------------------------
# GitLab API mock — handles both python-gitlab SDK and curl calls
# ---------------------------------------------------------------------------
REPOS_ROOT = Path("/repos")


@app.get("/api/v4/projects/{project_id}")
async def gitlab_get_project(project_id: int, request: Request):
    record_call("gitlab", "GET", f"/api/v4/projects/{project_id}")
    name = _mock_config["project_name"]
    ns = _mock_config["project_namespace"]
    host = request.headers.get("host", "mock-services:9000")
    return {
        "id": project_id,
        "name": name,
        "path": name,
        "path_with_namespace": f"{ns}/{name}",
        "default_branch": _mock_config["default_branch"],
        "http_url_to_repo": f"http://{host}/{ns}/{name}.git",
        "ssh_url_to_repo": f"git@{host}:{ns}/{name}.git",
        "web_url": f"http://{host}/{ns}/{name}",
        "namespace": {"id": 1, "name": ns, "path": ns, "full_path": ns},
    }


@app.get("/api/v4/projects/{project_id}/issues/{issue_iid}")
async def gitlab_get_issue(project_id: int, issue_iid: int):
    record_call("gitlab", "GET", f"/api/v4/projects/{project_id}/issues/{issue_iid}")
    return {
        "iid": issue_iid,
        "title": f"Test Issue #{issue_iid}",
        "description": "Test issue for mock integration testing",
        "state": "opened",
        "project_id": project_id,
    }


@app.post("/api/v4/projects/{project_id}/issues/{issue_iid}/notes")
async def gitlab_create_issue_note(project_id: int, issue_iid: int, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {"body": (await request.form()).get("body", "")}
    record_call("gitlab", "POST", f"/api/v4/projects/{project_id}/issues/{issue_iid}/notes", body)
    return {"id": int(time.time() * 1000), "body": body.get("body", ""), "created_at": datetime.utcnow().isoformat()}


@app.post("/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes")
async def gitlab_create_mr_note(project_id: int, mr_iid: int, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {"body": (await request.form()).get("body", "")}
    record_call("gitlab", "POST", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes", body)
    return {"id": int(time.time() * 1000), "body": body.get("body", "")}


@app.post("/api/v4/projects/{project_id}/merge_requests")
async def gitlab_create_mr(project_id: int, request: Request):
    body = await request.json()
    record_call("gitlab", "POST", f"/api/v4/projects/{project_id}/merge_requests", body)
    mr_iid = _mock_config["mr_iid"]
    host = request.headers.get("host", "mock-services:9000")
    ns = _mock_config["project_namespace"]
    name = _mock_config["project_name"]
    return {
        "iid": mr_iid,
        "id": mr_iid * 100,
        "title": body.get("title", "Test MR"),
        "description": body.get("description", ""),
        "state": "opened",
        "draft": body.get("draft", False),
        "source_branch": body.get("source_branch", ""),
        "target_branch": body.get("target_branch", "main"),
        "web_url": f"http://{host}/{ns}/{name}/-/merge_requests/{mr_iid}",
        "project_id": project_id,
    }


@app.get("/api/v4/projects/{project_id}/merge_requests/{mr_iid}")
async def gitlab_get_mr(project_id: int, mr_iid: int, request: Request):
    record_call("gitlab", "GET", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}")
    host = request.headers.get("host", "mock-services:9000")
    ns = _mock_config["project_namespace"]
    name = _mock_config["project_name"]
    return {
        "iid": mr_iid,
        "id": mr_iid * 100,
        "title": "Test MR",
        "description": "",
        "state": "opened",
        "draft": True,
        "source_branch": "codify/test",
        "target_branch": "main",
        "web_url": f"http://{host}/{ns}/{name}/-/merge_requests/{mr_iid}",
        "project_id": project_id,
        "diff_refs": {
            "base_sha": "abc123",
            "head_sha": "def456",
            "start_sha": "abc123",
        },
    }


@app.put("/api/v4/projects/{project_id}/merge_requests/{mr_iid}")
async def gitlab_update_mr(project_id: int, mr_iid: int, request: Request):
    # Handle both JSON and form-encoded bodies (entrypoint.sh uses curl --data-urlencode)
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)
    record_call("gitlab", "PUT", f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}", body)
    host = request.headers.get("host", "mock-services:9000")
    ns = _mock_config["project_namespace"]
    name = _mock_config["project_name"]
    return {
        "iid": mr_iid,
        "id": mr_iid * 100,
        "title": body.get("title", "Test MR"),
        "description": body.get("description", ""),
        "state": "opened",
        "draft": False,
        "web_url": f"http://{host}/{ns}/{name}/-/merge_requests/{mr_iid}",
    }


@app.get("/api/v4/projects/{project_id}/merge_requests")
async def gitlab_list_mrs(project_id: int, request: Request):
    """List MRs — used by entrypoint.sh to search for existing MR by source_branch."""
    params = dict(request.query_params)
    record_call("gitlab", "GET", f"/api/v4/projects/{project_id}/merge_requests", extra={"params": params})
    host = request.headers.get("host", "mock-services:9000")
    ns = _mock_config["project_namespace"]
    name = _mock_config["project_name"]
    mr_iid = _mock_config["mr_iid"]
    return [{
        "iid": mr_iid,
        "id": mr_iid * 100,
        "title": "Test MR",
        "state": "opened",
        "source_branch": params.get("source_branch", "codify/test"),
        "target_branch": "main",
        "web_url": f"http://{host}/{ns}/{name}/-/merge_requests/{mr_iid}",
    }]


@app.get("/api/v4/projects/{project_id}/repository/branches/{branch_name:path}")
async def gitlab_get_branch(project_id: int, branch_name: str):
    record_call("gitlab", "GET", f"/api/v4/projects/{project_id}/repository/branches/{branch_name}")
    return {
        "name": branch_name,
        "commit": {"id": "abc123def456", "message": "Initial commit"},
        "merged": False,
        "protected": branch_name == "main",
    }


@app.post("/api/v4/projects/{project_id}/repository/branches")
async def gitlab_create_branch(project_id: int, request: Request):
    body = await request.json()
    record_call("gitlab", "POST", f"/api/v4/projects/{project_id}/repository/branches", body)
    return {
        "name": body.get("branch", "new-branch"),
        "commit": {"id": "abc123def456", "message": "Initial commit"},
    }


@app.get("/api/v4/version")
async def gitlab_version():
    record_call("gitlab", "GET", "/api/v4/version")
    return {"version": "17.0.0-mock", "revision": "mock"}


@app.get("/api/v4/user")
async def gitlab_current_user():
    record_call("gitlab", "GET", "/api/v4/user")
    return {"id": 1, "username": "mock-bot", "name": "Mock Bot", "is_admin": False}


# ---------------------------------------------------------------------------
# Git Smart HTTP Backend — serves git clone/push via git http-backend CGI
# ---------------------------------------------------------------------------

async def _handle_git_request(repo_path: str, request: Request) -> Response:
    """Process a git HTTP request via git http-backend CGI."""
    record_call("git", request.method, request.url.path)

    # Map URL path to filesystem
    # repo_path examples: test-group/test-project.git/info/refs
    parts = repo_path.split("/")

    # Find the .git part to split repo name from path_info
    repo_dir = None
    path_info = ""
    for i, part in enumerate(parts):
        if part.endswith(".git"):
            repo_dir = "/".join(parts[: i + 1])
            path_info = "/" + "/".join(parts[i + 1 :]) if i + 1 < len(parts) else "/"
            break

    if not repo_dir:
        return Response(content="Repository not found", status_code=404)

    repo_fs_path = REPOS_ROOT / repo_dir
    if not repo_fs_path.exists():
        return Response(content=f"Repository {repo_dir} not found", status_code=404)

    # Build CGI environment
    query_string = str(request.url.query) if request.url.query else ""
    env = {
        **os.environ,
        "GIT_PROJECT_ROOT": str(REPOS_ROOT),
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": f"/{repo_dir}{path_info}",
        "QUERY_STRING": query_string,
        "REQUEST_METHOD": request.method,
        "CONTENT_TYPE": request.headers.get("content-type", ""),
        "CONTENT_LENGTH": request.headers.get("content-length", ""),
        "REMOTE_USER": "oauth2",
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_CONTENT_ENCODING": request.headers.get("content-encoding", ""),
    }

    body = await request.body()

    proc = await asyncio.create_subprocess_exec(
        "git", "http-backend",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(input=body)

    if stderr:
        logger.warning(f"git http-backend stderr: {stderr.decode(errors='replace')}")

    if not stdout:
        return Response(content="Empty response from git", status_code=500)

    # Parse CGI response: headers separated from body by \r\n\r\n
    header_end = stdout.find(b"\r\n\r\n")
    if header_end == -1:
        header_end = stdout.find(b"\n\n")
        separator_len = 2
    else:
        separator_len = 4

    if header_end == -1:
        return Response(content=stdout, media_type="application/octet-stream")

    raw_headers = stdout[:header_end].decode(errors="replace")
    response_body = stdout[header_end + separator_len:]

    # Parse CGI headers
    status_code = 200
    headers = {}
    for line in raw_headers.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("status:"):
            status_str = line.split(":", 1)[1].strip()
            status_code = int(status_str.split()[0])
        elif ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip()] = val.strip()

    return Response(
        content=response_body,
        status_code=status_code,
        headers=headers,
    )


@app.api_route("/git/{repo_path:path}", methods=["GET", "POST"])
async def git_http_handler_prefixed(repo_path: str, request: Request):
    """Git HTTP backend at /git/ prefix."""
    return await _handle_git_request(repo_path, request)


@app.middleware("http")
async def git_catch_all_middleware(request: Request, call_next):
    """Catch-all middleware for git HTTP requests at /{namespace}/{project}.git/...

    entrypoint.sh constructs URLs like http://host/{path_with_namespace}.git
    so git requests arrive at /{ns}/{project}.git/info/refs etc.
    We intercept these before they 404.
    """
    path = request.url.path
    # Check if path contains .git/ — indicates a git HTTP request
    git_idx = path.find(".git/")
    if git_idx > 0 and not path.startswith("/api/") and not path.startswith("/mock/") and not path.startswith("/git/"):
        # Strip leading / and route to git handler
        repo_path = path[1:]  # remove leading /
        return await _handle_git_request(repo_path, request)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Startup — initialize bare git repositories
# ---------------------------------------------------------------------------

def _init_git_repos(force: bool = False):
    """Create bare git repos with initial commits for testing."""
    ns = _mock_config["project_namespace"]
    name = _mock_config["project_name"]
    repo_path = REPOS_ROOT / ns / f"{name}.git"

    if repo_path.exists():
        if not force:
            logger.info(f"Repo already exists: {repo_path}")
            return
        import shutil
        shutil.rmtree(repo_path)
        logger.info(f"Removed existing repo: {repo_path}")

    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(repo_path)], check=True, capture_output=True)

    # Enable receive.denyCurrentBranch (bare repos don't have this issue, but be safe)
    subprocess.run(["git", "config", "--file", str(repo_path / "config"), "http.receivepack", "true"], check=True, capture_output=True)

    # Create initial commit using a temp clone
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "clone", str(repo_path), tmpdir], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@codify.test"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=tmpdir, check=True, capture_output=True)

        # Create initial file
        readme = Path(tmpdir) / "README.md"
        readme.write_text("# Test Project\n\nThis is a test repository for mock integration testing.\n")

        subprocess.run(["git", "add", "."], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=tmpdir, check=True, capture_output=True)

    logger.info(f"Initialized repo: {repo_path}")


@app.post("/mock/reset-git")
async def reset_git_repos():
    """Reset git repos to initial state (delete all branches except main)."""
    _init_git_repos(force=True)
    return {"status": "reset"}


@app.on_event("startup")
async def startup():
    _init_git_repos()
    logger.info("Mock services ready")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
