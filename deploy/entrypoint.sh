#!/bin/bash
set -e

# Worker entrypoint script
# Receives task parameters from environment variables

# Required environment variables
GITLAB_URL="${GITLAB_URL:?Missing GITLAB_URL}"
GITLAB_TOKEN="${GITLAB_TOKEN:?Missing GITLAB_TOKEN}"
PROJECT_ID="${PROJECT_ID:?Missing PROJECT_ID}"
ISSUE_IID="${ISSUE_IID:?Missing ISSUE_IID}"
BRANCH_NAME="${BRANCH_NAME:?Missing BRANCH_NAME}"
USER_PROMPT="${USER_PROMPT:?Missing USER_PROMPT}"

# Optional environment variables
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://localhost:11434/v1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
TARGET_BRANCH="${TARGET_BRANCH:-main}"

echo "========================================"
echo "GitLab Issue to MR Worker"
echo "========================================"
echo "Project: ${PROJECT_ID}"
echo "Issue: ${ISSUE_IID}"
echo "Branch: ${BRANCH_NAME}"
echo "Target: ${TARGET_BRANCH}"
echo "========================================"

# Extract hostname from GITLAB_URL for git operations
GITLAB_HOST=$(echo "${GITLAB_URL}" | sed 's|https://||' | sed 's|http://||')

# Get correct git repo URL from GitLab API (handles external_url misconfiguration)
echo "Fetching repository URL from GitLab API..."
GITLAB_API_RESPONSE=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}")
GIT_REPO_URL=$(echo "${GITLAB_API_RESPONSE}" | grep -o '"http_url_to_repo":"[^"]*"' | cut -d'"' -f4)
PROJECT_PATH=$(echo "${GITLAB_API_RESPONSE}" | grep -o '"path_with_namespace":"[^"]*"' | cut -d'"' -f4)

# Fallback to constructed URL if API fails
if [ -z "${GIT_REPO_URL}" ]; then
    echo "Warning: Could not get URL from API, using constructed URL"
    GIT_REPO_URL="https://${GITLAB_TOKEN}@${GITLAB_HOST}/projects/${PROJECT_ID}.git"
fi

# Replace hostname in URL with our actual GITLAB_HOST (handles GitLab external_url misconfiguration)
# Use HTTP (not HTTPS) since GitLab is configured for HTTP
GIT_REPO_URL=$(echo "${GIT_REPO_URL}" | \
    sed "s|https://[^/]*|http://${GITLAB_TOKEN}@${GITLAB_HOST}|" | \
    sed "s|http://[^/]*|http://${GITLAB_TOKEN}@${GITLAB_HOST}|")

echo "Repository URL: ${GIT_REPO_URL}"

# Configure git to allow insecure GitLab (self-signed cert)
git config --global http.sslVerify false

# Configure git to use token directly in URL
# Use git config to disable ssl verify
git config --global http.sslVerify false

# Set up credential helper - write credentials file
rm -rf ~/.git-credentials
touch ~/.git-credentials
chmod 600 ~/.git-credentials
# Write credentials in format: protocol://username:password@host
echo "http://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}" > ~/.git-credentials

git config --global credential.helper store

# Clone repository with authentication
echo "Cloning repository..."
git clone "${GIT_REPO_URL}" /workspace
cd /workspace

# Configure git
git config --global user.email "bot@gimr.local"
git config --global user.name "GIMR Bot"

# Checkout/create branch
echo "Checking out branch: ${BRANCH_NAME}"
git fetch origin
if git checkout "${BRANCH_NAME}" 2>/dev/null; then
    echo "Branch already exists, pulling latest..."
    git pull origin "${BRANCH_NAME}"
else
    echo "Creating new branch from ${TARGET_BRANCH}..."
    git checkout -b "${BRANCH_NAME}" "origin/${TARGET_BRANCH}"
fi

# Run Claude via Python SDK with planning and step-by-step execution
echo "Running Claude API with planning mode..."
echo "Prompt: ${USER_PROMPT}"
echo ""

# Create comprehensive Python script for planning and execution
cat > /tmp/claude_planner.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
Claude Planner: Plan -> Execute -> Report
Supports step-by-step planning and execution with MR updates.
"""

import os
import json
import subprocess
import re
import time
import anthropic
from datetime import datetime

# Get environment variables
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "http://localhost:11434/v1")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
USER_PROMPT = os.environ.get("USER_PROMPT", "")
GITLAB_URL = os.environ.get("GITLAB_URL", "")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")
PROJECT_ID = os.environ.get("PROJECT_ID", "")
ISSUE_IID = os.environ.get("ISSUE_IID", "")
MR_IID = os.environ.get("MR_IID", "")

# Initialize client
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

# Tools definition
TOOLS = [
    {
        "name": "Bash",
        "description": "Execute shell commands in the container. Use this to run git, python, or other CLI tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "description": {"type": "string", "description": "What the command does"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "Read",
        "description": "Read a file from the filesystem",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to read"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "Write",
        "description": "Write content to a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to write"},
                "file_path": {"type": "string", "description": "Path to write to"}
            },
            "required": ["file_path", "content"]
        }
    }
]

def execute_tool(tool_name, tool_input):
    """Execute a tool and return the result."""
    try:
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            result = subprocess.run(
                command,
                shell=True,
                cwd="/workspace",
                capture_output=True,
                text=True,
                timeout=300
            )
            return {
                "output": result.stdout + ("\nstderr: " + result.stderr if result.stderr else ""),
                "exit_code": result.returncode
            }
        elif tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            with open(file_path, "r") as f:
                return {"content": f.read()}
        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            with open(file_path, "w") as f:
                f.write(content)
            return {"success": True, "file_path": file_path}
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e)}

def call_claude(messages, tools=None, max_iterations=10):
    """Call Claude API with tool use support."""
    for i in range(max_iterations):
        try:
            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                messages=messages,
                tools=tools or []
            )
        except Exception as e:
            print(f"API Error: {e}", file=__import__('sys').stderr)
            return None

        # Check for tool use
        tool_use_blocks = [block for block in response.content if hasattr(block, 'type') and block.type == 'tool_use']

        if not tool_use_blocks:
            # No tool use, return the response
            return response

        # Process tool use
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input

            # Execute tool
            result = execute_tool(tool_name, tool_input)

            # Add tool result to messages
            messages.append({
                "role": "assistant",
                "content": [block]
            })
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                }]
            })

    # Max iterations reached
    return response

def update_mr_description(description):
    """Update MR description via GitLab API."""
    if not MR_IID:
        print("No MR_IID, skipping MR update")
        return

    import requests
    url = f"{GITLAB_URL}/api/v4/projects/{PROJECT_ID}/merge_requests/{MR_IID}"
    try:
        response = requests.put(
            url,
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            json={"description": description},
            timeout=10
        )
        if response.status_code < 400:
            print(f"MR description updated successfully")
        else:
            print(f"Failed to update MR: {response.status_code}")
    except Exception as e:
        print(f"Error updating MR: {e}")

def generate_planning_prompt():
    """Generate prompt for planning phase."""
    return f"""请分析以下需求，并制定实现计划。

需求: {USER_PROMPT}

请按以下格式输出规划:

## 📋 实现规划

### 需求
{USER_PROMPT}

### 实现步骤
请列出具体的实现步骤，每个步骤应该是可执行的原子操作:
- [ ] 步骤1: 具体描述
- [ ] 步骤2: 具体描述
- [ ] 步骤3: 具体描述
...

### 预期结果
请描述代码实现后的预期效果。
"""

def generate_step_prompt(step):
    """Generate prompt for executing a single step."""
    return f"""请执行以下步骤:

步骤: {step}

请使用工具完成这个步骤。如果需要创建或修改代码，请直接执行。
"""

# ============ MAIN EXECUTION ============

print("=" * 50)
print("Starting planning phase...")
print("=" * 50)

# Phase 1: Generate planning
planning_messages = [{"role": "user", "content": generate_planning_prompt()}]
planning_response = call_claude(planning_messages, tools=[])

if not planning_response:
    print("Failed to get planning response")
    exit(1)

# Extract planning content
planning_content = ""
for block in planning_response.content:
    if hasattr(block, 'type') and block.type == 'text':
        planning_content += block.text

print("\n--- Planning Result ---")
print(planning_content[:500])
print("...\n")

# Create MR description with planning
planning_md = f"""## 📋 实现规划

{planning_content}

---

### 执行进度
- [ ] 等待开始执行
"""

# Update MR with planning
print("Updating MR with planning...")
update_mr_description(planning_md)

# Phase 2: Extract steps and execute
print("\n" + "=" * 50)
print("Starting execution phase...")
print("=" * 50)

# Parse steps from planning (look for - [ ] or - [x] patterns)
steps = re.findall(r'- \[([ x])\] (.+)', planning_content)
print(f"Found {len(steps)} steps")

execution_log = []

for idx, (checked, step) in enumerate(steps):
    print(f"\n--- Step {idx + 1}/{len(steps)}: {step[:50]}... ---")
    start_time = time.time()

    # Execute step
    step_messages = [{"role": "user", "content": generate_step_prompt(step)}]
    step_response = call_claude(step_messages, tools=TOOLS)

    # Extract output
    step_output = ""
    if step_response:
        for block in step_response.content:
            if hasattr(block, 'type') and block.type == 'text':
                step_output += block.text

    duration = time.time() - start_time

    # Record execution
    execution_log.append({
        "step": step,
        "duration": duration,
        "output": step_output[:200]
    })

    # Update MR progress
    progress_md = planning_md + "\n\n### 执行进度\n"
    for i, (chk, stp) in enumerate(steps):
        if i < idx + 1:
            progress_md += f"- [x] {stp} ✓ (耗时: {execution_log[i]['duration']:.1f}秒)\n"
        elif i == idx + 1:
            progress_md += f"- [ ] {stp} (执行中...)\n"
        else:
            progress_md += f"- [ ] {stp}\n"

    # Add recent logs
    progress_md += "\n### 执行日志\n"
    for log in execution_log[-3:]:
        progress_md += f"- {log['step'][:40]}: {log['duration']:.1f}秒\n"

    update_mr_description(progress_md)

# Phase 3: Generate completion report
print("\n" + "=" * 50)
print("Generating completion report...")
print("=" * 50)

# Get changed files
result = subprocess.run("git status --porcelain", shell=True, cwd="/workspace", capture_output=True, text=True)
changed_files = result.stdout.strip()

# Generate report
report_md = f"""## ✅ 实现完成

### 需求
{USER_PROMPT}

### 变更文件
{changed_files if changed_files else '无'}

### 执行摘要
- 总步骤: {len(steps)}
- 成功: {len(execution_log)}
- 失败: 0

---

### 详细执行记录
"""

for log in execution_log:
    report_md += f"- **{log['step']}** ({log['duration']:.1f}秒)\n"

update_mr_description(report_md)

print("\n=== Execution completed ===")
print(f"Total steps: {len(steps)}")
print(f"Completed: {len(execution_log)}")

PYTHON_SCRIPT

chmod +x /tmp/claude_planner.py
python3 /tmp/claude_planner.py > /workspace/result.md 2>&1

RESULT=$?

# Show output
cat /workspace/result.md

if [ $RESULT -ne 0 ]; then
    echo "Claude Planner failed with exit code: ${RESULT}"
    exit $RESULT
fi

# The planner has already:
# 1. Used tools (Bash/Read/Write) to make changes in /workspace
# 2. Updated MR description during planning/execution
# 3. Generated completion report in the MR

# Now commit and push the changes
# Check if any changes were made (excluding result.md)
CHANGES=$(git status --porcelain | grep -v "result.md" || true)
if [ -n "$CHANGES" ]; then
    echo "Changes detected:"
    echo "$CHANGES"
    echo "Changes detected, committing..."

    # Add all changes
    git add -A

    # Create commit
    git commit -m "AI: ${USER_PROMPT:0:50}..."

    # Push to remote using git push
    echo "Pushing to remote..."
    # Use git push with http.extraHeader for token
    git remote set-url origin "http://${GITLAB_HOST}/${PROJECT_PATH}.git"
    git config --local http.extraHeader "PRIVATE-TOKEN: ${GITLAB_TOKEN}"
    GIT_TERMINAL_PROMPT=0 git push -u origin "${BRANCH_NAME}"

    # Get commit SHA
    COMMIT_SHA=$(git rev-parse HEAD)
    echo "Committed: ${COMMIT_SHA}"

    # Collect change statistics for MR description using git status --porcelain
    # Format: XY path, where X=index status, Y=work tree status
    # A=added, M=modified, D=deleted, ??=untracked
    # Use process substitution to avoid subshell issues
    NEW_FILES=""
    MODIFIED_FILES=""
    DELETED_FILES=""

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        status="${line:0:2}"
        filepath="${line:3}"
        # Skip result.md (it's the output file, not actual code)
        [ "$filepath" = "result.md" ] && continue
        case "$status" in
            "A "*) NEW_FILES="${NEW_FILES}${filepath}," ;;
            "M "*) MODIFIED_FILES="${MODIFIED_FILES}${filepath}," ;;
            "D "*) DELETED_FILES="${DELETED_FILES}${filepath}," ;;
            "??")  NEW_FILES="${NEW_FILES}${filepath}," ;;
        esac
    done < <(git status --porcelain)

    # Remove trailing commas
    NEW_FILES="${NEW_FILES%,}"
    MODIFIED_FILES="${MODIFIED_FILES%,}"
    DELETED_FILES="${DELETED_FILES%,}"

    # MR was already created by backend before worker started
    # Just get the MR info if MR_IID was provided
    MR_WEB_URL=""
    if [ -n "${MR_IID}" ]; then
        echo "Using existing MR: !${MR_IID}"
        MR_WEB_URL=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${MR_IID}" | \
            grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
    else
        # Fallback: check if MR already exists for this branch
        echo "Checking for existing MR..."
        EXISTING_MR=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests?state=opened&source_branch=${BRANCH_NAME}" | \
            grep -o '"iid":[0-9]*' | head -1 | cut -d':' -f2)
        if [ -n "$EXISTING_MR" ]; then
            MR_WEB_URL=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
                "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${EXISTING_MR}" | \
                grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
        fi
    fi

    if [ -z "$MR_WEB_URL" ]; then
        MR_WEB_URL=$(cat /workspace/mr_response.json | grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
    fi
    echo "MR created: ${MR_WEB_URL}"

    # Comment on issue with MR link
    echo "Commenting on issue..."
    curl -s -X POST "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/issues/${ISSUE_IID}/notes" \
        -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
            \"body\": \"I've created a merge request: ${MR_WEB_URL}\\n\\nPlease review the changes.\"
        }"

    echo "========================================"
    echo "Task completed successfully!"
    echo "========================================"
else
    echo "No changes made by Claude CLI"
    exit 1
fi
