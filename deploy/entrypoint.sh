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

# Run Claude via Python SDK
echo "Running Claude API..."
echo "Prompt: ${USER_PROMPT}"
echo ""

# Create Python script to call Claude API with Tool Use support
cat > /tmp/claude_call.py << 'PYTHON_SCRIPT'
import os
import json
import subprocess
import anthropic
from anthropic import Anthropic

# Get environment variables
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "http://localhost:11434/v1")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
USER_PROMPT = os.environ.get("USER_PROMPT", "")

# Initialize client
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

# Define available tools for the container
# Container has access to git, curl, file operations
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
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            messages=messages,
            tools=tools or []
        )

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

# Main execution
try:
    messages = [{"role": "user", "content": USER_PROMPT}]
    response = call_claude(messages, TOOLS)

    # Extract text output
    output = []
    for block in response.content:
        if hasattr(block, 'type') and block.type == 'text':
            output.append(block.text)

    if output:
        print('\n'.join(output))
    else:
        print(f"# No text output. Content: {response.content}", file=__import__('sys').stderr)
        exit(1)
except Exception as e:
    print(f"Error: {e}", file=__import__('sys').stderr)
    exit(1)
PYTHON_SCRIPT

python /tmp/claude_call.py > /workspace/result.md 2>&1

RESULT=$?
cat /workspace/result.md

if [ $RESULT -ne 0 ]; then
    echo "Claude API failed with exit code: ${RESULT}"
    exit $RESULT
fi

# Parse result and create files if needed
# Handle tool calls in output (various formats from different APIs)
if grep -q '<tool' /workspace/result.md || grep -q '<tool_call>' /workspace/result.md || grep -q 'echo ' /workspace/result.md; then
    echo "Processing tool calls..."
    python3 << 'PYTHON_PARSE'
import re
import subprocess
import os

with open('/workspace/result.md', 'r') as f:
    content = f.read()

executed = False

# Try to find bash commands in markdown code blocks
bash_code_matches = re.findall(r'```bash\n(.*?)```', content, re.DOTALL)
for cmd in bash_code_matches:
    cmd = cmd.strip()
    print(f"Executing bash from code block: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, cwd='/workspace', capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Bash executed successfully")
            executed = True
        else:
            print(f"Bash error: {result.stderr}")
    except Exception as e:
        print(f"Bash exception: {e}")

# Try to find echo commands: echo 'content' > file
echo_matches = re.findall(r'echo\s+[\'"](.+?)[\'"]\s+>\s+(\S+)', content)
for echo_content, file_path in echo_matches:
    try:
        with open(f'/workspace/{file_path}', 'w') as f:
            f.write(echo_content)
        print(f"Created file from echo: {file_path}")
        executed = True
    except Exception as e:
        print(f"Echo file error: {e}")

# Try to find <tool name="bash"> or <tool name="shell">
bash_matches = re.findall(r'name="(bash|shell)"\s*>\s*(.+?)(?:</tool>|$)', content, re.DOTALL)
for tool_name, cmd in bash_matches:
    cmd = cmd.strip()
    print(f"Executing bash: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, cwd='/workspace', capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Bash executed successfully")
            executed = True
        else:
            print(f"Bash error: {result.stderr}")
    except Exception as e:
        print(f"Bash exception: {e}")

# Try to find file creation tools (various names including Write)
# Format 1: <tool name="Write" path="file">content</tool>
file_matches = re.findall(r'name="(write_file|Create a file|Write|file_create|create_file|MkFile)"\s+(path|file_path)="([^"]+)"\s*>\s*(.+?)(?:</tool>|$)', content, re.DOTALL)
for tool_name, attr_name, file_path, file_content in file_matches:
    try:
        with open(f'/workspace/{file_path}', 'w') as f:
            f.write(file_content.strip())
        print(f"Created file: {file_path}")
        executed = True
    except Exception as e:
        print(f"Write file error: {e}")

# Format 2: <tool name="Write">file.txt\ncontent</tool> (no path attribute)
file_matches2 = re.findall(r'<tool\s+name="(Write|write_file|Create a file)">\s*(.+?)\s*</tool>', content, re.DOTALL)
for tool_name, file_content in file_matches2:
    # Try to parse "filename\ncontent"
    lines = file_content.strip().split('\n')
    if len(lines) >= 2:
        file_path = lines[0].strip()
        file_content = '\n'.join(lines[1:]).strip()
        if file_path and not file_path.startswith('<'):
            try:
                with open(f'/workspace/{file_path}', 'w') as f:
                    f.write(file_content)
                print(f"Created file (no attr): {file_path}")
                executed = True
            except Exception as e:
                print(f"Write file error: {e}")

# Try XML format: <tool_call><tool_name>create_file</tool_name><args><param name="path">...</param>...
xml_matches = re.findall(r'<tool_name>(create_file|write_file)</tool_name>\s*<args>\s*<param name="path">([^<]+)</param>\s*<param name="content">([^<]+)</param>', content, re.DOTALL)
for tool_name, file_path, file_content in xml_matches:
    try:
        with open(f'/workspace/{file_path}', 'w') as f:
            f.write(file_content.strip())
        print(f"Created file (XML): {file_path}")
        executed = True
    except Exception as e:
        print(f"Write file error: {e}")

# Try simpler XML format without namespace
xml_matches2 = re.findall(r'<tool\s+name="file_create"\s+path="([^"]+)"\s*>\s*(.+?)(?:\n|$)', content, re.DOTALL)
for file_path, file_content in xml_matches2:
    try:
        with open(f'/workspace/{file_path}', 'w') as f:
            f.write(file_content.strip())
        print(f"Created file (simple): {file_path}")
        executed = True
    except Exception as e:
        print(f"Write file error: {e}")

if executed:
    print("Tool execution completed")
PYTHON_PARSE
fi

# Check if any changes were made (including untracked files)
# Use git status --porcelain to detect both tracked and untracked changes
CHANGES=$(git status --porcelain)
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

    # Build file info string (single line)
    FILE_INFO=""
    [ -n "$NEW_FILES" ] && FILE_INFO="${FILE_INFO}New: ${NEW_FILES%,} | "
    [ -n "$MODIFIED_FILES" ] && FILE_INFO="${FILE_INFO}Mod: ${MODIFIED_FILES%,} | "
    [ -n "$DELETED_FILES" ] && FILE_INFO="${FILE_INFO}Del: ${DELETED_FILES%,}"
    # If no code files found, show result.md as fallback
    if [ -z "$FILE_INFO" ]; then
        FILE_INFO="New: result.md (output)"
    else
        FILE_INFO="${FILE_INFO%, }"
    fi

    # Build MR title and description (single line for JSON reliability)
    MR_TITLE="AI: ${USER_PROMPT:0:50}"
    # Simple format without special chars that break JSON
    MR_DESC="REQ: ${USER_PROMPT} | FILES: ${FILE_INFO} | CLOSES #${ISSUE_IID}"

    # Check if MR already exists for this branch
    echo "Checking for existing MR..."
    EXISTING_MR=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests?state=opened&source_branch=${BRANCH_NAME}" | \
        grep -o '"iid":[0-9]*' | head -1 | cut -d':' -f2)

    if [ -n "$EXISTING_MR" ]; then
        echo "MR already exists: #${EXISTING_MR}, updating..."
        # Update existing MR description
        curl -s -X PUT "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${EXISTING_MR}" \
            -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{
                \"description\": \"${MR_DESC}\"
            }" > /workspace/mr_response.json
        MR_WEB_URL=$(curl -s -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${EXISTING_MR}" | \
            grep -o '"web_url":"[^"]*"' | cut -d'"' -f4)
    else
        echo "Creating new Merge Request..."
        # Use GitLab API to create MR
        curl -s -X POST "${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests" \
            -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{
                \"source_branch\": \"${BRANCH_NAME}\",
                \"target_branch\": \"${TARGET_BRANCH}\",
                \"title\": \"${MR_TITLE}\",
                \"description\": \"${MR_DESC}\",
                \"remove_source_branch\": true
            }" > /workspace/mr_response.json
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
