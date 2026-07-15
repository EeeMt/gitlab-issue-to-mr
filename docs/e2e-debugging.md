# E2E 集成测试调试指南

本文档记录调试 Codify (Codify) E2E 测试时发现的问题和解决方案。

## 环境配置

### 配置文件说明

| 文件 | 用途 |
|------|------|
| `deploy/.env.test` | 测试环境配置（用于 docker-compose） |
| `backend/.env` | 本地开发配置（用于测试脚本） |

**重要**：
- `.env.test` 包含真实的 GitLab Token 和 API Key
- 测试脚本从 `backend/.env` 读取配置
- `.env.test` 不应提交到版本控制（已配置 .gitignore）

### 关键配置项

```bash
# deploy/.env.test
GITLAB_URL=http://192.168.50.129:8080        # GitLab 地址
GITLAB_BOT_TOKEN=glpat-xxx                    # GitLab Personal Access Token
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic  # API 地址
ANTHROPIC_API_KEY=sk-cp-xxx                   # Anthropic/MiniMax API Key
ANTHROPIC_MODEL=MiniMax-M2.5                  # 使用的模型
```

### 重新构建镜像

修改代码后必须重新构建 Docker 镜像：

```bash
# 1. 重新构建 worker 镜像（修改 entrypoint.sh 后需要）
docker build -f deploy/Dockerfile.worker-java21-maven -t codify-worker/java21-maven:2026.07 .

# 2. 重新构建 backend 镜像（修改 worker.py 后需要）
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .

# 3. 重启服务
cd deploy && docker-compose up -d backend

# 或者一次性构建所有镜像
cd deploy && docker-compose up -d --build
```

**注意**：修改以下文件后需要重新构建：
- `deploy/entrypoint.sh` → 重新构建 worker 镜像
- `backend/app/core/worker.py` → 重新构建 backend 镜像

---

## 常见问题及解决方案

### 1. Token 泄露问题

**症状**：错误日志中暴露了 GitLab Token (`glpat-xxx`) 或 API Key (`sk-xxx`)

**原因**：
- 日志直接输出敏感信息
- 数据库错误信息未脱敏

**解决方案**：
```python
# backend/app/core/worker.py
import re

def sanitize_sensitive_data(text: str) -> str:
    if not text:
        return text
    # 移除 GitLab tokens
    text = re.sub(r'glpat-[a-zA-Z0-9\-]{10,}', '[GITLAB_TOKEN]', text)
    # 移除 API keys
    text = re.sub(r'sk-(?:cp|ant|api)-[a-zA-Z0-9\-]{10,}', '[API_KEY]', text)
    # 移除 null 字节
    text = text.replace('\x00', '')
    return text
```

**在以下位置调用**：
- 存储 error_message 前
- 存储 task_logs 前
- 发送到外部系统（Issue 评论）前

---

### 2. Shell Heredoc 语法错误

**症状**：Python 脚本报 `SyntaxError: unmatched ')'`

**原因**：在 `<<'PYTHON_SCRIPT'` heredoc 内错误放置了 bash 代码

**示例**：
```bash
# 错误：bash 代码在 heredoc 内
cat > /tmp/script.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
...
# Get changed files - 这应该是 bash，不是 Python！
result=$(git status --porcelain)
...
PYTHON_SCRIPT  # heredoc 结束

# 正确：bash 代码在 heredoc 之后
cat > /tmp/script.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
print("hello")
PYTHON_SCRIPT

# bash 代码
result=$(git status --porcelain)
```

---

### 3. 数据库编码错误

**症状**：`CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8": 0x00`

**原因**：日志中包含 null 字节 (`\x00`)

**解决方案**：
```python
# 在 sanitize_sensitive_data 中添加
text = text.replace('\x00', '')
text = ''.join(char if ord(char) < 0xFFFD else '?' for char in text)
```

---

### 4. 任务状态卡住

**症状**：任务状态一直是 `running`，但容器已退出

**原因**：容器退出后，backend 未正确更新任务状态

**调试方法**：
```bash
# 检查任务状态
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT id, status FROM tasks ORDER BY id DESC LIMIT 5;"

# 检查容器状态
docker ps -a | grep codify

# 检查容器日志
docker logs <container_id>
```

---

### 5. Docker 容器调试技巧

**查看容器输出**：
```bash
# 容器运行时
docker logs -f <container_name>

# 容器已退出 - 仍可查看
docker logs <container_id>
```

**交互式调试**：
```bash
# 进入运行中的容器
docker exec -it <container_name> /bin/bash

# 调试 Python 脚本 - 输出重定向到文件
docker run your-image python3 script.py > output.md 2>&1
```

**常见容器名称模式**：
- Worker: `codify-{task_id}-p{project_id}-i{issue_iid}`
- Backend: `codify-e2e-backend`
- Database: `codify-e2e-postgres`

---

### 6. 日志截断问题

**症状**：错误信息不完整，只看到部分日志

**原因**：日志长度限制太小

**解决方案**：
```python
# 增加日志存储长度
task.error_message = sanitized_logs[-1000:]  # 原来是 500
log_entry = TaskLog(message=sanitized_logs[-4000:])  # 原来是 2000
```

---

### 7. API 兼容性问题

**症状**：Anthropic SDK 调用 MiniMax API 失败

**注意**：
- MiniMax API 兼容 Anthropic SDK (`base_url=https://api.minimaxi.com/anthropic`)
- 但需要确认 API Key 格式正确

**调试**：
```python
import anthropic
client = anthropic.Anthropic(
    api_key="your-key",
    base_url="https://api.minimaxi.com/anthropic"
)
response = client.messages.create(
    model="MiniMax-M2.5",
    max_tokens=10,
    messages=[{"role": "user", "content": "hi"}]
)
```

---

## 调试命令速查

```bash
# 1. 查看后端日志
docker logs codify-e2e-backend --tail 100
docker logs codify-e2e-backend --tail 100 2>&1 | grep -i "task\|error"

# 2. 查看数据库任务状态
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 3;"

# 3. 查看任务日志（完整输出）
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT message FROM task_logs WHERE task_id = <id>;"

# 4. 查看 GitLab Issue 评论（真实 GitLab 地址）
GITLAB_TOKEN="glpat-xxx"  # 从 deploy/.env.test 获取
GITLAB_URL="http://192.168.50.129:8080"
curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/1/issues/1/notes"

# 5. 查看 MR 状态
curl -s -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/1/merge_requests/1"

# 6. 查看当前运行的容器
docker ps -a | grep codify

# 7. 重新构建 worker 镜像（修改 entrypoint.sh 后需要）
docker build -f deploy/Dockerfile.worker-java21-maven -t codify-worker/java21-maven:2026.07 .

# 8. 重新构建 backend 镜像（修改 worker.py 后需要）
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .

# 9. 重启服务
cd deploy && docker-compose up -d backend

# 10. 运行 E2E 测试（跳过 Docker 启动）
cd backend && python3 tests/gitlab_e2e/test_integration.py --skip-startup

# 11. 查看 .env.test 配置
cat deploy/.env.test | grep -v "^#" | grep -v "^$"
```

### 常用 GitLab API 端点（开发环境）

```
GitLab 地址: http://192.168.50.129:8080
项目 ID: 1 (root/codify_test)

# Issue 相关
GET  /api/v4/projects/1/issues              # 列出 Issue
GET  /api/v4/projects/1/issues/{iid}        # 获取 Issue
POST /api/v4/projects/1/issues               # 创建 Issue
GET  /api/v4/projects/1/issues/{iid}/notes  # 获取 Issue 评论

# MR 相关
GET  /api/v4/projects/1/merge_requests              # 列出 MR
GET  /api/v4/projects/1/merge_requests/{iid}        # 获取 MR
GET  /api/v4/projects/1/repository/commits?ref_name=branch  # 查看提交

# 项目相关
GET  /api/v4/projects/1                     # 获取项目信息
GET  /api/v4/projects/1/repository/branches # 列出分支
```

---

## 测试检查清单

运行 E2E 测试后，验证以下项目：

- [ ] Issue 评论显示开始通知
- [ ] Issue 评论显示完成通知（带 MR 链接）
- [ ] MR 有实际提交（SHA 不为 null）
- [ ] MR 无冲突
- [ ] 任务状态为 completed（不是 running/failed）
- [ ] 错误日志中无 Token 泄露

---

## 相关文件

### 核心代码
- `backend/app/core/worker.py` - Worker 执行器（包含脱敏函数）
- `deploy/entrypoint.sh` - Worker 入口脚本

### 测试相关
- `backend/tests/gitlab_e2e/test_integration.py` - E2E 测试（包含 Step 10 验证）
- `backend/tests/mock_e2e/test_integration.py` - Mock 测试（无需真实 GitLab）
- `backend/tests/unit/test_priority.py` - P0.1 功能测试

### 配置文件
- `deploy/.env.test` - 测试环境配置（docker-compose 使用）
- `deploy/docker-compose.yml` - Docker Compose 配置
- `deploy/Dockerfile.worker-java21-maven` - Java 21/Maven Worker runtime 镜像构建
- `deploy/Dockerfile.backend` - Backend 镜像构建
