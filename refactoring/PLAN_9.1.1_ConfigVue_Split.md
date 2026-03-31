# 9.1.1 Config.vue 拆分计划

## 现状分析

### 文件规模
| 部分 | 行数 | 说明 |
|------|------|------|
| Template | ~868 行 | 7 个 Tab 页 |
| Script | ~1020 行 | 状态、方法、API 调用 |
| **总计** | **~2145 行** | 严重过大 |

### Tab 结构
```
Config.vue
├── Header (1-33)           ~33 行  - 标题、摘要
├── runtime (36-264)        ~230 行 - 运行时设置 + 共享页面访问
├── gitlab (266-548)        ~283 行 - GitLab 连接 + Webhook 管理
├── notifications (550-555) ~6 行   - MattermostNotificationsPanel
├── auth (557-774)          ~218 行 - OIDC 设置 + OidcDiagnosticsPanel
├── worker (776-778)        ~3 行   - WorkerSettingsPanel
├── maintenance (780-804)   ~25 行  - 重置操作
└── prompt-templates (805-868) ~63 行 - 模板管理
```

### 已有可复用组件
- `MattermostNotificationsPanel.vue` (820行) - 已是独立组件
- `OidcDiagnosticsPanel.vue` (363行) - 已是独立组件
- `WorkerSettingsPanel.vue` (567行) - 已是独立组件

### 共享状态 (Script)
- `formValue` - 配置表单数据
- `lastLoadedValue` - 原始数据快照
- `sectionSaving` - 各 section 保存状态
- `sectionFieldKeys` - 各 section 字段映射
- 多个 `ref` 状态和 `computed` 属性

---

## 拆分方案

### 目标文件结构
```
frontend/src/views/config/
├── Config.vue                    # 聚合层 (Tab 容器 + Header) ~400行
├── RuntimeSettingsPanel.vue      # 运行时设置 ~250行
├── GitLabSettingsPanel.vue       # GitLab 设置 + Webhook ~350行
├── AuthSettingsPanel.vue         # OIDC 设置 ~250行
├── MaintenancePanel.vue          # 维护操作 ~50行
├── PromptTemplatesPanel.vue      # 模板管理 ~150行
└── useConfigForm.ts             # 共享表单状态 Composable ~200行
```

### 新建组件清单

| 组件 | 行数 | 职责 |
|------|------|------|
| `useConfigForm.ts` | ~200 | 表单状态、脏检测、保存逻辑 |
| `RuntimeSettingsPanel.vue` | ~250 | 调度器设置 + 共享页面访问 |
| `GitLabSettingsPanel.vue` | ~350 | GitLab 连接 + Webhook 管理 |
| `AuthSettingsPanel.vue` | ~250 | OIDC 设置 (不含 Diagnostics) |
| `MaintenancePanel.vue` | ~50 | 重置/刷新操作 |
| `PromptTemplatesPanel.vue` | ~150 | 模板 CRUD |
| `Config.vue` (重构后) | ~400 | Header + Tab 容器 |

---

## 拆分步骤

### Phase A: 创建表单状态 Composable

**新建:** `frontend/src/views/config/useConfigForm.ts`

```typescript
// 导出类型
export type ConfigForm = { ... }
export type ConfigSectionKey = 'runtime' | 'sharedPages' | 'gitlab' | 'oidc' | 'session'
export type TestState = { type: 'success' | 'error', message: string }

// 导出共享状态
export function useConfigForm() {
  // formValue, lastLoadedValue
  // sectionSaving
  // isSectionDirty, snapshotSection
  // handleSaveSection
  // handleClearSecret
  // resetSection
  // reloadConfig
  return { formValue, lastLoadedValue, sectionSaving, ... }
}
```

### Phase B: 创建 RuntimeSettingsPanel

**新建:** `frontend/src/views/config/RuntimeSettingsPanel.vue`

- 提取 runtime tab 内容
- 使用 `useConfigForm()` 获取状态
- Props: `isMobile`
- Emits: 无 (状态通过 composable 共享)

### Phase C: 创建 GitLabSettingsPanel

**新建:** `frontend/src/views/config/GitLabSettingsPanel.vue`

- 提取 gitlab tab 内容
- 包含 webhook 表格逻辑
- 依赖 `useConfigForm()` + 额外的 webhook 状态

### Phase D: 创建 AuthSettingsPanel

**新建:** `frontend/src/views/config/AuthSettingsPanel.vue`

- 提取 auth tab (不含 OidcDiagnosticsPanel)
- 保留 OIDC form ref 和测试逻辑

### Phase E: 创建 MaintenancePanel

**新建:** `frontend/src/views/config/MaintenancePanel.vue`

- 提取 maintenance tab
- 包含 handleReload, handleReset

### Phase F: 创建 PromptTemplatesPanel

**新建:** `frontend/src/views/config/PromptTemplatesPanel.vue`

- 提取 prompt-templates tab
- 包含模板 CRUD 逻辑和 VariableEditor

### Phase G: 重构 Config.vue

**修改:** `frontend/src/views/Config.vue`

- 保留: Header, summaryItems, activeConfigTab
- 导入并使用各子组件
- 移除已迁移的 script 代码
- 清理不再需要的 imports

---

## 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 状态共享复杂 | 中 | 使用 composable 统一管理 |
| 表单验证规则迁移 | 中 | 保持原有 rules 结构 |
| API 调用耦合 | 中 | 封装在一个 composable |
| 循环依赖 | 低 | composable 只返回 reactive 状态 |
| 功能回归 | 高 | 保留完整测试，自动化测试 |

---

## 实施顺序

```
Week 1:
  Day 1-2: 创建 useConfigForm.ts，提取共享状态
  Day 3-4: RuntimeSettingsPanel
  Day 5:   GitLabSettingsPanel (部分)

Week 2:
  Day 1-2: GitLabSettingsPanel (完成)
  Day 3:   AuthSettingsPanel
  Day 4:   MaintenancePanel + PromptTemplatesPanel
  Day 5:   重构 Config.vue，清理整合

Week 3 (备用):
  - Bug 修复
  - 测试补充
  - 文档更新
```

---

## 验证方式

```bash
# 1. 确认 Config.vue 行数减少
wc -l frontend/src/views/Config.vue  # 目标 < 500

# 2. 确认新文件行数合理
wc -l frontend/src/views/config/*.vue
wc -l frontend/src/views/config/*.ts

# 3. 运行 Vitest
cd frontend && npx vitest run

# 4. 类型检查
cd frontend && npx vue-tsc --noEmit

# 5. E2E 测试 (Config 页面)
cd backend && pytest tests/e2e/ -v -k "config"
```

---

## 注意事项

1. **保持 API 兼容性** - 不改变任何 API 调用
2. **保持 UI 一致性** - 不改变样式和布局
3. **保持功能等价** - 重构后行为完全一致
4. **增量提交** - 每完成一个阶段就提交
5. **测试先行** - 考虑添加 Config.vue 的组件测试

---

## 依赖关系

```
useConfigForm.ts (必须先创建)
    ├── RuntimeSettingsPanel.vue
    ├── GitLabSettingsPanel.vue
    ├── AuthSettingsPanel.vue
    ├── MaintenancePanel.vue
    └── PromptTemplatesPanel.vue
              │
              └── Config.vue (最后重构)
```
