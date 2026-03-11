# E2E 集成测试调试指南

本文档记录调试 GIMR (GitLab Issue to MR Bot) E2E 测试时发现的问题和解决方案。

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
docker exec gimr-postgres psql -U gimr -d gimr -c "SELECT id, status FROM tasks ORDER BY id DESC LIMIT 5;"

# 检查容器状态
docker ps -a | grep gimr

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
- Worker: `gimr-{task_id}-p{project_id}-i{issue_iid}`
- Backend: `gimr-backend`
- Database: `gimr-postgres`

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
docker logs gimr-backend --tail 100

# 2. 查看数据库任务状态
docker exec gimr-postgres psql -U gimr -d gimr -c "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 3;"

# 3. 查看任务日志
docker exec gimr-postgres psql -U gimr -d gimr -c "SELECT message FROM task_logs WHERE task_id = <id>;"

# 4. 查看 GitLab Issue 评论
curl -s -H "PRIVATE-TOKEN: xxx" "http://gitlab/api/v4/projects/1/issues/1/notes"

# 5. 查看 MR 状态
curl -s -H "PRIVATE-TOKEN: xxx" "http://gitlab/api/v4/projects/1/merge_requests/1"

# 6. 重新构建镜像
docker build -f deploy/Dockerfile.worker -t gitlab-issues-to-mr-worker:latest .

# 7. 重启服务
docker-compose -f deploy/docker-compose.yml up -d backend

# 8. 运行 E2E 测试
cd backend && python3 test_integration_e2e.py --skip-startup
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

- `backend/app/core/worker.py` - Worker 执行器（包含脱敏函数）
- `deploy/entrypoint.sh` - Worker 入口脚本
- `backend/test_integration_e2e.py` - E2E 测试（包含 Step 10 验证）
