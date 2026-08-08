# Multi-Harness Engine 深度 Review 报告

- **Review 范围**: `af279c66..HEAD`(分支 v2),349 文件 / ~19,200 行新增
- **日期**: 2026-08-07
- **重点维度**: 正确性 bug、规范一致性(对照 Phase 0-2 规格文档)、测试质量
- **验证**: 静态阅读 + 全量单测 + 真实 fixture 复现
- **基线**: review 前 `make test-backend` 2272 passed、`make test-frontend` 1513 passed 全绿

## 结论摘要

多 Harness 引擎整体设计扎实:canonical event 协议、writer 的 flock + 严格不变量、attempt 幂等 ingest、Runtime Bundle 内容寻址与校验、session 命名空间、凭据生命周期都符合规格且测试充分。**发现的 bug 主要集中在 Codex 路径**(作为新引擎覆盖不足),以及**前端 WorkerSettings 面板保存丢失**这两个方向。

## 严重度统计

| 级别 | 数量 | 已修复 | 未修(待决策) |
|---|---|---|---|
| P0 | 0 | - | - |
| P1 | 4 | 4 | 0 |
| P2 | 6 | 5 | 1 |
| P3 | 8 | 1 | 7 |

---

## P1(已全部修复)

### 1. Codex translator 缺失失败路径映射 —— 已修复
- **位置**: `deploy/worker-entrypoint/harness/adapters/codex_events.py` `translate()`
- **问题**: 生产 translator 只处理 `thread.started/item.started/item.completed/turn.completed`,把 `error`、`turn.failed`、error-item 全部降为 `diagnostic`。而 Phase 0 冻结的 fixtures(由 `scripts/harness-probes/codex_fixture_mapper.py` 定义)明确要求 `error → provider.retry`、`turn.failed → harness.failed`(带失败分类)、compaction 提示 → `context.compacted`。
- **证据**: 用真实 fixture `codex/authentication_failure/stdout.jsonl` 复现——修复前 translator 产出 10 条 `diagnostic`,无 `provider.retry`、无 `harness.failed`;最终任务只能以 runner 合成的 `protocol_error` 失败,丢失 auth/rate-limit 分类,UI/分析无法区分。
- **影响**: codex 认证失败/限流等被错误归类为通用 `protocol_error`/`engine_error`;fixtures 描述的失败分类生产代码无法产出。
- **修复**: 增加 `error → provider.retry`(侧文件计数)、`turn.failed → harness.failed`(按消息分类:401/429/sandbox)、`item.completed error → context.compacted/capability_warning`、`turn.started` 跳过、第二次 `thread.started → diagnostic(session_resumed)`;`harness.completed` 增加幂等守卫(多 turn 不再崩溃)。
- **测试**: 新增 `test_codex_fixture_stream_translates_to_canonical_events`(17 场景参数化,全部精确前缀匹配)+ `test_codex_authentication_failure_preserves_failure_taxonomy` + `test_codex_rate_limited_preserves_failure_taxonomy`。修复后全部 31 条 codex adapter 测试通过。
- **多 turn 语义(第三轮修复)**: 将 codex harness 终态**推迟到流结束**由 adapter 补发(`codex_adapter_emit_terminal`),使"最后 turn 的成败为准"。`turn.completed → turn.failed` 判定为**失败**(harness.failed + run.failed),对齐"绝不猜测成功"。这同时修掉了 context_compaction 的多 turn 偏离(现在在最后一个 turn 发 harness.completed)。新增合成 fixture `turn_failed_after_completion` 钉死该语义(见下)。

### 2. WorkerSettingsPanel harness 字段保存丢失 —— 已修复
- **位置**: `frontend/src/components/config/WorkerSettingsPanel.vue` `buildWorkerProfilePayload()`;`frontend/src/api/index.ts` `WorkerProfilePayload`
- **问题**: UI 编辑 `enabled_harnesses`/`default_harness_key`/`harness_constraints`,但 payload 与类型均未包含这三个字段;后端 `backend/app/api/worker_profiles.py:100-104` 明确接受。每次保存静默还原为 DB 旧值,harness 编辑器功能完全失效。
- **测试缺口**: `WorkerSettingsPanel.spec.ts` 无任何 harness 断言,故未暴露。
- **修复**: payload + 类型补上三字段;spec 新增 "loads and saves the enabled/default harness fields" 断言。

### 3. codex `--verify` 校验错误二进制 —— 已修复
- **位置**: `deploy/worker-kit/verify-runtime.sh`;`deploy/offline-bundle/scripts/verify-worker-runtime.sh`
- **问题**: codex 路径只挂载并设置 `CODIFY_CODEX_BIN`,从未设置 `CODIFY_HARNESS_CLI_BIN`;而 `entrypoint.worker.sh:84` 只从 `CODIFY_CLAUDE_BIN` 派生它,且 Kit 已移除 adapters,`verification.sh:65` 退化为执行 claude 二进制 `--version`。codex-only runtime image 无法通过 preflight;含 claude 的镜像则校验了错误的版本门。
- **修复**: codex 分支同时设置 `CODIFY_HARNESS_CLI_BIN=<container path>`。

### 4. harness_registry 声明 codex `run_text=True` 与 adapter/规格矛盾 —— 已修复
- **位置**: `backend/app/core/harness_registry.py` `SYSTEM_CAPABILITIES["codex"]`
- **问题**: registry 声明 codex `run_text=True`,但 manifest 声明 `false`、`codex_adapter_run_text` 返回 1、规格 Task 2.9 明确"Codex 不支持 run_text"。该值被冻结进 Task Snapshot(`worker_profiles.py:571` 的 `harness_config_snapshot`)并展示在 `harness_options` 能力里,使 snapshot/UI 声称 codex 支持 run_text。
- **修复**: `SYSTEM_CAPABILITIES["codex"]["run_text"] = False`。
- **附带**: 同一处 `manifest.json` codex `task_skills=false` 与 adapter(确实物化 skills)及 Task 2.9 矛盾,一并修为 `true`。

---

## P2(2 已修复,4 待决策)

### 5. codex_adapter_normalize_result 校验空转 —— 已修复
- **位置**: `deploy/worker-entrypoint/harness/adapters/codex.sh` `codex_adapter_normalize_result()`
- **问题**: jq 程序是对象字面量模板(不读取输入),仅校验文件是合法 JSON;不像 claude 版校验 schema/harness_key/adapter_version/cli_version/status。
- **修复**: 改为与 claude 一致的真实字段校验(兼容 completed/failed/cancelled/protocol_error)。

### 6. session_namespace 缺少认证域与工作区身份输入 —— ✅ 已澄清 + 文档对齐(2026-08-08)
- **位置**: `backend/app/core/harness_sessions.py:24-32`;`docs/architecture/worker-harness-contract-v1.md`
- **问题**: contract 原列 5 个输入(Harness、Endpoint fingerprint、**认证域**、**工作区身份**、Adapter state major);实现只用 harness + fingerprint + state-major。
- **澄清**: 经评估,**3 输入是正确形态**,理由见架构报告 §视角 B——workspace identity 由 `issue_id` 隐含(冗余);authentication domain 若按凭据实例定义会使凭据轮换重置会话(有害),真正该防的跨认证方式续接已由 endpoint fingerprint 的非敏感 auth-scheme 字段覆盖。
- **修复**: 契约文档改为 3 输入定义并写明理由;`session_namespace_for` 补注释指向契约。**不增加 namespace 输入**。
- **影响评估**: 无代码行为变化,纯文档/注释对齐。

### 7. 064 迁移对遗留明文 api_key 的 backfill 会生成不可解密的 credential —— 已修复
- **位置**: `backend/alembic/versions/064_multi_harness_runtime.py:193-219`;`backend/app/core/model_credentials.py`
- **问题**: 直接把 `ai_providers.api_key` 拷入 `model_credentials.secret_encrypted`。Fernet 加密 key 往返正确;但 `_decrypt_provider_api_key`(providers.py:246-254)显式支持**遗留明文** api_key,这类行迁移后 `credential_secret()` 的 `decrypt_config_secret(明文)` 会抛 `ConfigEncryptionError`,credential 不可用。
- **修复**: `credential_secret()` 增加与 `_decrypt_provider_api_key` 一致的明文回退(解密失败返回原值)。该修复对**已执行过迁移**的环境同样生效(运行时自愈)。新增 `test_legacy_plaintext_secret_resolves_like_encrypted`。

### 8. TaskFormDrawer 重复实现 backend 的 wire-protocol 兼容规则 —— 已修复
- **位置**: `frontend/src/components/TaskFormDrawer.vue`;`backend/app/api/providers.py`;`backend/app/core/harness_registry.py`
- **问题**: `HARNESS_WIRE_PROTOCOLS` + `providerCompatibleWithHarness` 复制了 `backend/app/core/harness_registry.py:55-56` 的规则,前端自行过滤 provider/禁选 harness/自动调整选中项。规格 Phase 2 Task 2.2 明确"Frontend 不得自行复制 Backend 的 Harness/Endpoint 兼容规则;直接消费 `list_harness_options`"。
- **修复**: 后端新增 `compatible_harness_keys()` 反向查询(registry),provider 序列化返回 `compatible_harnesses`;前端删除硬编码 `HARNESS_WIRE_PROTOCOLS`,兼容判断改为成员检查。补 registry 单测与 spec fixtures。

### 9. cli_version_range 声明但无运行时强制 —— 待决策
- **位置**: `deploy/worker-entrypoint/harness/manifest.json`(claude `>=2.1.33 <3.0.0`,codex `>=0.146.0 <0.160.0`)
- **问题**: contract 说 "Version ranges are a fast startup check";但 claude 仅硬编码下限 2.1.33(无上界),codex 完全未校验版本范围,只查二进制存在 + digest。`cli_version_range` 字段无任何代码读取。
- **建议**: 在 adapter `verify_runtime` 内解析 manifest 的 range 并拒绝范围外版本。**未修**(需决策 range 解析与错误语义)。

### 10. projector tail 对撕裂末行 strict-decode 崩溃 —— 已修复
- **位置**: `backend/app/core/worker_event_projector.py:368`(及 backfill 路径)
- **问题**: `result.output.decode("utf-8", errors="strict")`。若崩溃产生的不完整末行含拆分多字节字符,整个 chunk decode 抛 UnicodeDecodeError,ingest 永久失败;绕过了 `iter_complete_jsonl_records` 的 remainder/重试设计。
- **修复**: 两处 `errors="strict"` 改为 `errors="replace"`。撕裂末行留在 remainder 不消费,下次 tail 从 cursor offset 重读原始字节;无 remainder 时 chunk 必为合法 UTF-8,replace 为空操作,字节核算不受影响。新增 `test_tail_survives_torn_final_line_with_split_multibyte_char`。

---

## P3(已修复 1,记录 7)

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 11 | `deploy/worker-entrypoint/delivery.sh:54` | `[ ! -x ] && [ ! -f ]` 漏检"存在但不可执行"的 validator | ✅ 修复为 `[ ! -x ]` |
| 12 | `harness/events.py` `emit()` | 每次全量重读 event.jsonl(O(n²));撕裂末行会让下次 emit 失败 | 记录 |
| 13 | `harness/adapters/claude.sh` | `adapter_terminate` 从未被 runner 调用,终止依赖 ci-claude 内部清理 + signal trap | 记录 |
| 14 | `deploy/worker-entrypoint/repository.sh:226` | `.git` 条件 chown 吞掉失败(`2>/dev/null \|\| true`) | 记录 |
| 15 | `frontend/src/views/CreateIssue.vue:891` | default-harness 回退 `'claude'` 可能在 enabled 为空时越界(064 backfill 保证 enabled 恒非空,实际风险低) | 记录 |
| 16 | `frontend/src/views/TaskView.vue:859` | `hasClaudeSession` 仅镜像 claude lineage,codex 会话下提示过期(展示层) | 记录 |
| 17 | `harness_attempts.py` `ingest_canonical_event` | 每次 ingest 重放全部 receipts(O(n²)) | 记录 |
| 18 | `worker_event_projector.py` `_pending_tool_log_by_id` | 内存 map;tool.completed 晚于 100 个工具后 DB 回退搜索可能漏配 | 记录 |

---

## 测试质量(WS8)

**扎实**: 协议层 `test_harness_protocol.py`、attempt `test_harness_attempts.py`(SQLite 真实执行)、session `test_harness_sessions.py`、claude adapter `test_claude_harness_adapter.py`(16 fixture 参数化精确对比)、`test_harness_event_fixtures.py`(完整性/清洗/回放)均高质量。

**缺口(已部分补上)**:
- codex adapter 此前只测成功路径,无失败 fixture 回归 → **已补**(见 P1.1)。
- `WorkerSettingsPanel.spec.ts` 无 harness 断言 → **已补**(见 P1.2)。
- `test_064_migration.py` 是纯静态内容检查,不执行迁移;`test_harness_migration_guard.py` 只测拒绝路径。多 harness 迁移链(063-067)的 upgrade/downgrade/backfill 往返**未在 CI 真实验证**(依赖手工一次性 PostgreSQL)。**未修**。
- fixtures 测试对 codex 走 `codex_fixture_mapper.py --check` 而非生产 translator(修复 P1.1 后两者已对齐)。

---

## 验证记录

- Review 前全量单测: backend **2272 passed**, frontend **1513 passed**。
- 第一轮修复后全量单测: backend **2290 passed**, frontend **1514 passed**。
- 第二轮修复后全量单测: backend **2293 passed**, frontend **1514 passed**, vue-tsc 干净。
- 用真实 fixture `codex/authentication_failure` + `codex/rate_limited` 复现并验证 P1.1:修复前后 translator 输出对比见 PR 记录。
- 改动 shell/python 脚本通过 `bash -n` / `py_compile`。

## 未修复项后续建议

1. **cli_version_range 运行时强制**(P2)建议补进 adapter `verify_runtime`,与 digest 校验并列。
2. ~~session_namespace 增加认证域/工作区输入~~ —— **已澄清(2026-08-08)**:保持 3 输入,契约文档已对齐并写明理由,见第 6 项。

## 第二轮修复(2026-08-07,用户指定)

将三项 P2 由"待决策"转为已修复:
- **064 明文 backfill**: `credential_secret()` 增加明文回退(运行时自愈,对已迁移环境同样生效)。
- **TaskFormDrawer wire-protocol**: 后端新增 `compatible_harness_keys()` + provider 序列化 `compatible_harnesses`,前端删除本地 map。
- **projector strict-decode**: 两处 `errors="strict"` → `errors="replace"`。

第二轮修复后验证: backend **2293 passed**, frontend **1514 passed**, vue-tsc 干净。

## 第三轮修复(2026-08-07,用户指定):codex 终态语义钉死

用户确认 `turn.completed → turn.failed` 应判**失败**(agent 未完成工作)。实现与影响:

- **终态推迟到流结束**: `codex_events.py` 不再内联发 harness 终态,只持久化最后 turn 终态(`.codex-terminal-type`/`.codex-terminal-line`)与结果文件;`codex.sh` 新增 `codex_adapter_emit_terminal` 在流结束后按"最后 turn 为准"补发单个 harness 终态;`codex-run.sh` 按终态决定退出码(completed→0,failed→1)。
- **顺带修复 multi-turn 偏离**: context_compaction 现在在最后一个 turn 发 harness.completed(与 fixture mapper 一致),`EXACT_PREFIX_EXCLUDED` 已移除。
- **fixture**: 新增合成样本 `codex/turn_failed_after_completion`(`collection_state=synthetic-offline-contract-sample`,因无 provider 凭据无法现场采集,README 已注明),钉死"后到的 turn.failed 覆盖先到的完成"。mapper 同步加 `last_turn_failed` 逻辑 + FAILURE_KIND 条目。
- **测试**: translator 31 条(codex adapter)+ fixture 42 条全过;新增 `codex_adapter_emit_terminal` 三个用例(completed/failed/noop)。

第三轮修复后验证: backend **2298 passed**, fixture 42 passed, codex adapter 31 passed。
