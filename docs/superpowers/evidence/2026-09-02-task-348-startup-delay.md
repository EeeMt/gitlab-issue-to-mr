# Task #348 启动前延迟调查

**调查日期：** 2026-09-02  
**调查对象：** [Task #348](http://192.168.50.129:8880/tasks/348)  
**调查范围：** 从任务创建到 Harness 发出首个 canonical `run.started`，以及页面首次显示事件流之间的延迟。  
**结论状态：** 已定位；本次只读排查未修改代码、配置或远端数据。

## 结论

Task #348 的主要延迟不是 Scheduler 排队，也不是模型接口等待，而是 V2 `mounted_kit` 运行模式在启动前执行了多次严格的 Worker Kit 内容校验：

1. Scheduler 领取任务前执行一次完整 readiness probe；
2. Worker 开始准备执行上下文后再次执行一次 readiness probe；
3. 实际任务容器创建后、启动前再执行一次针对真实容器挂载 Kit 的校验。

前两次 probe 各约 39 秒，真实容器启动前的校验约 38 秒。因而从创建任务到 Harness 的 `run.started` 事件约 130 秒，页面第一次显示事件约 135 秒。

页面上的“开始时间”不是 Harness 真正开始执行的时间：它表示 Task 生命周期进入 `RUNNING`。当前页面把 Worker 启动、Kit 校验、容器初始化和控制端点启动都计入了执行时长。

## 现场运行身份

- Host：`192.168.50.129`，`linux/amd64`
- 执行模式：`dual_canary`
- Worker Profile：`4 / v2-canary-0.6.11-four-harness`
- Runtime mode：`mounted_kit`
- Worker Kit：`0.6.11`
- Harness：Pi，CLI `0.84.2`，Adapter `2.0.0`
- Worker image：`127.0.0.1:5000/codify-worker/java21-maven`，使用当前 Profile 冻结的镜像 digest
- readiness TTL：远端环境未显式覆盖，使用默认 `900` 秒

该 Kit 的四个 Harness 可执行文件大小如下，总计 `839,706,624` bytes，约 840 MB：

| Harness | 大小 |
|---|---:|
| Codex | 311,001,136 bytes |
| OpenCode | 184,277,120 bytes |
| Claude | 239,896,272 bytes |
| Pi | 104,532,096 bytes |

完整 probe 不仅读取这些可执行文件，还会扫描 Kit 内容并对挂载文件进行 SHA-256 校验，因此实际 Docker archive I/O 不应只按四个可执行文件的总大小估算。

## 时间线

以下时间均已转换为 Asia/Shanghai；远端 Scheduler 日志和数据库原始时间为 UTC。

| 时间 | 阶段 | 耗时 | 证据与说明 |
|---|---|---:|---|
| 23:21:57.678 | Task 创建 | — | `tasks.created_at` |
| 23:21:59.314 | Scheduler 开始处理 Task | 创建后 1.6 秒 | Scheduler 已及时领取，不是队列等待 |
| 23:21:59.345–23:22:38.327 | Scheduler 领取前的严格 Kit probe | 约 39.0 秒 | Docker client 初始化到关闭；probe 在 claim 前执行 |
| 23:22:38.535 | Task 写入 `started_at` / 进入 `RUNNING` | — | 这是生命周期标记，不是 `run.started` |
| 23:22:38.625–23:23:17.193 | Worker 再次 readiness probe | 约 38.6 秒 | readiness 检查记录的开始和完成时间 |
| 23:23:17.233 | 创建 Harness attempt | — | `task-348-attempt-1-24d493d3e992` |
| 23:23:17.344–23:23:55.292 | 创建真实容器并完成启动前 Kit 校验 | 约 38.0 秒 | 容器创建后，校验通过后才允许启动 |
| 23:23:55.292 | 真实 Worker 容器启动 | — | Docker 日志 |
| 23:23:55.292–23:24:07.745 | 容器入口、仓库准备、Harness 控制端点启动 | 约 12.5 秒 | 期间 command pump 有控制端点未就绪的重试 |
| 23:24:07.745 | canonical `run.started` 发生 | 创建后约 130.1 秒 | Harness 正式开始执行 |
| 23:24:11.895–23:24:12.614 | 首条消息事件发生并写入 receipt | 创建后约 134.2–135.0 秒 | 页面约在 23:24:12 首次显示事件 |

Task 的 `run.started` 到 `run.completed` 仅约 32.8 秒，说明真正的 Harness/模型执行并未占用前面的两分钟。

## 根因对应的代码路径

### 1. Scheduler 在领取前执行 V2 严格 probe

Scheduler 的 Task 执行路径会先调用 runtime readiness gate，然后才将任务从可执行状态领取并写入运行状态。对于 V2 Runtime Contract，缓存的 `ready` 结果不能直接替代完整内容身份校验，而是调用确定性 Kit probe。

对应代码：[`backend/app/scheduler.py`](../../../backend/app/scheduler.py)。

### 2. V2 probe 会通过 Docker archive 读取并哈希整个 Kit

`worker_runtime_readiness` 使用停止状态的探测容器，以只读方式挂载 Kit，再通过 Docker archive API 读取文件内容。V2 的完整内容 inventory 会扫描 Kit 树，并对 manifest、launcher、entrypoint 以及所有存在的 Harness 文件做 SHA-256 校验。

对应代码：[`backend/app/core/worker_runtime_readiness.py`](../../../backend/app/core/worker_runtime_readiness.py)。

这条路径会把数百 MB 的远端 Docker I/O、归档解包和 Python 侧哈希计算放到 Task 启动关键路径上。Task #348 的两次 readiness probe 各约 39 秒，与该实现和远端日志完全对应。

### 3. Worker 在真实容器启动前再次校验挂载内容

Worker 创建真实任务容器后，不会直接启动，而是先调用 `inspect_mounted_kit_container` 对实际容器中的挂载 Kit 做最终校验。该步骤用于避免 Scheduler probe 与真实 Worker 容器之间的挂载内容发生变化，因此又产生约 38 秒延迟。

对应代码：[`backend/app/core/worker_task_lifecycle.py`](../../../backend/app/core/worker_task_lifecycle.py)。

### 4. `started_at` 与 `run.started` 的语义不同

`started_at` 在任务生命周期进入 `RUNNING` 时写入；而 `run.started` 是 Harness Adapter 初始化并开始产生 canonical event stream 后才发生。因此当前 Task 详情页的执行时长包含了启动前准备阶段，不能直接作为模型执行时长。

## 排除项

- **不是 Scheduler 排队：** 创建后约 1.6 秒就开始处理 Task；现场没有并发任务把 Scheduler 挤满。
- **不是调度轮询间隔：** Scheduler 轮询配置为秒级，实际领取延迟只有约 1.6 秒。
- **不是仓库准备：** Worker 原始日志中的 repository prepare/fetch 只有约 `1,245 ms`。
- **不是主要的模型 API 延迟：** `run.started` 之后到 Harness 完成约 32.8 秒；主要等待发生在事件流建立之前。
- **不是 readiness TTL 过期本身：** TTL 只提供普通的正向缓存语义；V2 的 Scheduler gate 明确要求重新做完整内容身份 probe，因此即使存在有效的 `ready` 记录，也不能绕过这条校验。

最近同一运行身份下的历史任务，创建到 `started_at` 多数也在约 39–43 秒，说明这部分是可重复的系统性开销，而非 Task #348 的偶发阻塞。

## 优化边界

本次未实施优化。若要缩短启动时间，需要在不破坏 V2 fail-closed 运行时身份保证的前提下重新设计校验边界，候选方向包括：

1. 给完整 probe 增加分阶段耗时指标，分别记录 archive 读取、全量 inventory、Harness 文件哈希和容器创建/删除耗时；
2. 对严格绑定的 image identity、Kit manifest identity 和安装 generation 复用可信结果，避免每个 Task 重复读取整个 Kit；
3. 评估 Scheduler probe 与真实容器启动前 probe 的职责是否可以合并，或把其中一次降级为轻量身份检查；
4. 保留真实容器启动前的最终 fail-closed 校验，除非能够证明缓存身份与实际挂载之间存在等价的原子性保证。

其中第 2、3 项会改变当前 V2 的安全/一致性边界，不能仅作为性能调优直接上线；第 1 项没有行为变化，适合作为下一步先行工作。

## 证据边界

本记录基于 Task #348 详情页、目标 Host 的 Scheduler/Docker 日志、Task/attempt/event receipt/raw log 数据库记录，以及当前 checkout 中的执行代码交叉核对。它证明了 Task #348 的具体延迟组成和当前实现的主要根因，不等同于对所有 Worker image、Runtime mode 或非 V2 Profile 的性能基准。
