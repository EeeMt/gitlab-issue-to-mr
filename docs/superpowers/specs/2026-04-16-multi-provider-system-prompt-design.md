# Multi AI Provider + System Prompt — Design Spec

**Date:** 2026-04-16
**Status:** Draft

## Problem

The system currently supports a single AI provider configuration (Anthropic base URL, API key, model, max turns) stored in `system_config`. Users running self-hosted models with limited compute want to configure multiple providers (e.g., "self-hosted-night" for off-hours, "cloud-api" for daytime) and select per task. Additionally, `claude -p` supports `--system-prompt` but the system has no way to configure it.

## Solution

1. New `ai_providers` database table storing named provider configurations
2. Each provider has: name, base_url, api_key (encrypted), model, max_turns, system_prompt, is_default flag
3. Tasks gain an optional `provider_id` FK — null means use system default
4. CRUD API for provider management
5. Frontend: new "AI Providers" tab in Config page, provider selector in task creation
6. Worker resolves provider from task → default → legacy fallback
7. System prompt passed via `APPEND_SYSTEM_PROMPT` env var → `ci-claude.sh` already passes it as `--append-system-prompt` to Claude CLI

## Data Model

### `ai_providers` Table

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Internal ID |
| `name` | VARCHAR(100) | UNIQUE, NOT NULL | Human-readable identifier, e.g. "self-hosted-night" |
| `base_url` | TEXT | NOT NULL | API endpoint URL |
| `api_key` | TEXT | NULLABLE | Encrypted API key (same encryption as system_config secrets) |
| `model` | VARCHAR(200) | NOT NULL | Model name, e.g. "claude-sonnet-4-20250514" |
| `max_turns` | INTEGER | NOT NULL, DEFAULT 20 | Max conversation turns (1–1000) |
| `system_prompt` | TEXT | NULLABLE | System prompt passed via `--system-prompt` to Claude CLI |
| `is_default` | BOOLEAN | NOT NULL, DEFAULT FALSE | Exactly one provider should be default |
| `created_at` | DATETIME | NOT NULL | Creation timestamp |
| `updated_at` | DATETIME | NOT NULL | Last update timestamp |

**Constraints:**
- `name` is unique — enforced at DB level
- `is_default` invariant: exactly one row with `is_default=true` at all times (enforced in application code, not DB constraint)
- `api_key` is encrypted at rest using existing `encrypt_config_secret()` / `decrypt_config_secret()` from `runtime_config.py`

### Task Table Change

Add column:
```
provider_id  INTEGER FK → ai_providers.id, NULLABLE, ON DELETE SET NULL
```

- `NULL` = use system default provider (the one with `is_default=true`)
- `ON DELETE SET NULL` ensures that deleting a provider doesn't cascade-delete tasks; affected tasks fall back to default

### Migration Strategy

Alembic migration (next sequential number):

1. Create `ai_providers` table
2. Add `provider_id` column to `tasks` table with FK
3. Data migration: read current `system_config` entries for `anthropic_base_url`, `anthropic_api_key`, `anthropic_model`, `claude_max_turns` and insert as a provider named `"default"` with `is_default=true`
4. Existing `system_config` anthropic_* entries are left in place for backward compatibility

## API Design

### Provider CRUD

All endpoints require admin authentication.

#### `GET /api/providers`

Returns list of all providers. API key is **never** returned; replaced with `api_key_configured: bool`.

Response:
```json
[
  {
    "id": 1,
    "name": "self-hosted",
    "base_url": "http://192.168.1.100:11434/v1",
    "api_key_configured": true,
    "model": "claude-sonnet-4-20250514",
    "max_turns": 20,
    "system_prompt": "You are a senior developer...",
    "is_default": true,
    "created_at": "2026-04-16T10:00:00Z",
    "updated_at": "2026-04-16T10:00:00Z"
  }
]
```

#### `POST /api/providers`

Create a new provider. If this is the first provider, automatically set `is_default=true`.

Request:
```json
{
  "name": "cloud-api",
  "base_url": "https://api.anthropic.com",
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514",
  "max_turns": 50,
  "system_prompt": "You are a code reviewer..."
}
```

Validation:
- `name`: required, 1–100 chars, unique, alphanumeric + hyphens + underscores
- `base_url`: required, valid HTTP/HTTPS URL
- `api_key`: optional (some self-hosted setups don't need auth)
- `model`: required, non-empty
- `max_turns`: optional (default 20), 1–1000
- `system_prompt`: optional, up to 10000 chars

#### `PATCH /api/providers/{id}`

Update provider fields. Only provided fields are updated. To clear `api_key`, send `"clear_api_key": true`. To clear `system_prompt`, send `"system_prompt": null`.

#### `DELETE /api/providers/{id}`

Delete a provider. Fails with 409 if the provider is used by any task in PENDING/QUEUED/RUNNING status. Fails with 409 if this is the only provider (system needs at least one). If deleting the default provider, the remaining provider with the lowest ID becomes default.

#### `POST /api/providers/{id}/set-default`

Set this provider as the system default. Clears `is_default` on all other providers.

### Task API Changes

#### `POST /api/tasks` (create task)

Add optional `provider_id` field:
```json
{
  "issue_id": 5,
  "user_prompt": "Implement the login page",
  "provider_id": 2
}
```

- If `provider_id` is provided, validate it exists
- If omitted or null, task uses system default

#### `GET /api/tasks/{id}` (task detail)

Include resolved provider info in response:
```json
{
  "id": 10,
  "provider_id": 2,
  "provider_name": "cloud-api",
  ...
}
```

### Legacy Compatibility

The `GET/PATCH /api/config/runtime` endpoints keep their `anthropic_*` fields. They continue to work for backward compatibility (CLI tools, scripts). If a default provider exists, runtime config reads from it. Runtime config writes update the default provider.

## Frontend Design

### Config Page: New "AI Providers" Tab

Replace the AI Provider section in WorkerSettingsPanel with a dedicated tab `AI Providers` in the Config page.

**Tab content:**

1. **Provider list** — NDataTable with columns: Name, Model, Base URL, Default (badge), Actions (Edit/Delete/Set Default)
2. **Create button** — Opens a drawer with the provider form
3. **Edit** — Same drawer, pre-populated
4. **Delete** — Popconfirm, blocked if provider is in use by active tasks
5. **Set Default** — Button in actions column, or a radio/star indicator

**Provider form (Drawer):**

| Field | Component | Notes |
|-------|-----------|-------|
| Name | NInput | Required, validated for uniqueness |
| Base URL | NInput | Required, placeholder: `http://localhost:11434/v1` |
| Model | NInput | Required, placeholder: `claude-sonnet-4-20250514` |
| Max Turns | NInputNumber | Range 1–1000, default 20 |
| API Key | NInput (password) | Optional; shows status badge if configured |
| System Prompt | NInput (textarea) | Optional, rows=6, placeholder hint about usage |

### WorkerSettingsPanel Changes

Remove: `anthropic_base_url`, `anthropic_api_key`, `anthropic_model`, `claude_max_turns` fields.
Keep: Docker configuration, concurrency settings, and other worker-related fields.

Add an info note: "AI Provider settings have moved to the AI Providers tab."

### Task Creation: Provider Selector

In the create-task form (IssueView drawer and CreateIssue page):

- Add NSelect for provider selection
- Options: `[{ label: "System Default (self-hosted)", value: null }, { label: "cloud-api (claude-sonnet-4)", value: 2 }, ...]`
- Default selection: null (system default)
- Fetch provider list via `GET /api/providers`

### TaskView / TaskMetadataPanel

Add a metadata row showing the provider used:
- Label: "AI Provider" with icon
- Value: Provider name, or "System Default" if provider_id is null
- Clickable link to Config > AI Providers tab

### i18n

Add keys to both `en.ts` and `zh-CN.ts`:

```
providers.title: 'AI Providers' / 'AI 模型服务'
providers.create: 'Add Provider' / '添加服务'
providers.name: 'Name' / '名称'
providers.baseUrl: 'Base URL' / '接口地址'
providers.model: 'Model' / '模型'
providers.maxTurns: 'Max Turns' / '最大轮次'
providers.apiKey: 'API Key' / 'API 密钥'
providers.systemPrompt: 'System Prompt' / '系统提示词'
providers.isDefault: 'Default' / '默认'
providers.setDefault: 'Set as Default' / '设为默认'
providers.deleteConfirm: 'Delete this provider?' / '确认删除此服务？'
providers.inUseError: 'Provider is in use by active tasks' / '该服务正在被任务使用中'
providers.systemDefault: 'System Default' / '系统默认'
```

## Worker / Entrypoint Changes

### `worker.py` — Provider Resolution

New method `_resolve_provider()`:

```python
async def _resolve_provider(self, db: AsyncSession, task: Task) -> AIProvider:
    """Resolve the AI provider for a task."""
    if task.provider_id:
        provider = await db.get(AIProvider, task.provider_id)
        if provider:
            return provider
    # Fall back to default provider
    result = await db.execute(
        select(AIProvider).where(AIProvider.is_default == True)
    )
    provider = result.scalar_one_or_none()
    if provider:
        return provider
    # Legacy fallback: build from settings
    settings = get_effective_settings()
    return AIProvider(
        name="legacy",
        base_url=settings.anthropic_base_url,
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        max_turns=settings.claude_max_turns,
        system_prompt=None,
    )
```

### `_build_container_env()` Changes

Replace direct `settings.*` reads with resolved provider:

```python
provider = await self._resolve_provider(db, task)
environment = {
    "ANTHROPIC_BASE_URL": provider.base_url,
    "ANTHROPIC_API_KEY": decrypt_if_needed(provider.api_key) or "",
    "ANTHROPIC_MODEL": provider.model,
    "CLAUDE_MAX_TURNS": str(provider.max_turns),
    "SYSTEM_PROMPT": provider.system_prompt or "",
    # ... other env vars unchanged
}
```

### `entrypoint.sh` Changes

Add system prompt support:

```bash
SYSTEM_PROMPT="${SYSTEM_PROMPT:-}"

# Build claude args
CLAUDE_ARGS="--model $ANTHROPIC_MODEL --max-turns $CLAUDE_MAX_TURNS"
if [ -n "$SYSTEM_PROMPT" ]; then
    CLAUDE_ARGS="$CLAUDE_ARGS --system-prompt \"$SYSTEM_PROMPT\""
fi

# Execute
claude -p "$PROMPT" $CLAUDE_ARGS
```

## Testing Strategy

### Backend Unit Tests

- Provider CRUD: create, read, update, delete
- Default provider logic: first provider auto-default, set-default clears others, delete-default promotes next
- Provider resolution: task with provider_id, task without (uses default), no providers (legacy fallback)
- Validation: duplicate name, invalid URL, max_turns range, system_prompt length
- Delete blocked when active tasks reference provider

### Frontend Unit Tests

- Provider list rendering
- Provider form validation
- Provider selector in task creation
- TaskMetadataPanel shows provider name

### E2E Tests

- Create a provider via Config page
- Set as default
- Create task with specific provider selected
- Verify task detail shows correct provider

## Migration Checklist

1. Alembic migration creates table + adds FK
2. Data migration reads `system_config` anthropic_* → inserts default provider
3. Worker uses `_resolve_provider()` instead of direct settings access
4. Frontend Config page gains AI Providers tab
5. Task creation forms gain provider selector
6. entrypoint.sh supports `--system-prompt`
7. Backward compatibility: runtime config API still works for anthropic_* fields
