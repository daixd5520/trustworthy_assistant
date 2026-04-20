# Nightly Dream Design

## 背景

`trustworthy_assistant` 目前已经具备以下基础能力：

- 基于 `CRON.json` 的定时任务调度
- 基于 `memory/daily/*.jsonl` 的按日对话摘要沉淀
- 基于 `memory/ledger/*.jsonl` 和 `MEMORY.md` 的长期记忆管理
- 基于 hybrid search 和向量检索的记忆召回

但当前记忆链路仍然偏被动：

- 对话结束后会落一条 digest，但不会在夜间对当天内容做系统性整理
- 用户长期偏好、持续项目、稳定约束的抽取仍然比较零散
- agent 缺少一层可持续累积的“服务经验”或“工作套路”沉淀

为了让 agent 随着用户使用逐步进化，需要在现有架构上增加一个类似 OpenClaw memory flush / background consolidation 思路的夜间整理机制。本文将该机制命名为 `Nightly Dream`。

## 目标

- 每天夜间为活跃用户作用域随机选择一个 `03:00-08:00` 之间的时间点
- 对“前一天”的对话 digest 和候选记忆进行一次后台整理
- 产出可 review 的 dream report
- 将值得长期保留的用户信息沉淀为结构化记忆
- 将值得复用的 agent 服务经验沉淀为独立 lessons
- 保持与当前 `cron`、`memory service`、`prompt builder` 架构兼容

## 非目标

- 第一版不自动修改 `SOUL.md`、`IDENTITY.md`、`AGENTS.md`
- 第一版不主动给用户发送夜间整理结果
- 第一版不自动执行外部工具或产生副作用操作
- 第一版不把所有推断都直接升级为 confirmed memory
- 第一版不追求复杂聚类或跨月知识图谱

## OpenClaw 对齐思路

从公开文档可确认，OpenClaw 至少具备以下与本设计相似的机制基础：

- `context` 与 `memory` 分离
- 有持久化 `cron` 任务调度
- 有 compaction 前的 silent memory flush

因此，本设计不追求“复刻一个新 runtime”，而是采用等价思路：

1. 用后台调度唤醒一次独立整理任务
2. 聚合当天短期记忆和对话摘要
3. 产出更稳定的长期记忆和服务经验
4. 写回可检索的持久化存储

## 当前系统现状

### 已有能力

- `runtime/cron.py`
  - 已支持基于 `CRON.json` 的 job 加载、调度、执行和状态持久化
- `memory/service.py`
  - 已支持 conversation digest 追加写入
  - 已支持 memory ledger upsert、冲突处理、markdown projection
  - 已支持 hybrid search 和向量检索
- `bookkeeping.py`
  - 已提供动态改写 `CRON.json` 的成熟范式，可复用到 dream 计划写入

### 当前限制

- 当前 `cron` 触发 turn 时，`channel="cron"` 分支会按 `agent_id` 聚合当日 digest，而不是按具体 `channel + user_id` 过滤
- 如果直接使用现有 cron turn 逻辑做夜间整理，多个用户可能会被混在同一次“做梦”里
- 当前长期记忆和 agent 经验没有明确分层，若直接混写进同一 ledger，语义会被污染

## 核心设计

### 设计原则

- 按用户作用域整理，而不是按 agent 全局整理
- 报告先行，写回可控
- 用户事实与 agent 经验分层存储
- 低风险、可回滚、可追溯
- 优先复用已有调度和 memory 体系

### 作用域

Nightly Dream 的最小整理单位定义为：

`(agent_id, channel, user_id, local_date)`

说明：

- `agent_id` 用于区分多 agent
- `channel` 用于区分微信、终端、企业微信等来源
- `user_id` 用于确保不同用户不混淆
- `local_date` 表示被整理的目标日期

### 时间语义

- 用户在 `2026-04-20` 当天产生的对话
- 不在白天立即进行 dream
- 在 `2026-04-21 03:00-08:00` 之间随机选择一个时间点整理

这样可以保证：

- 当天数据已经基本完整
- 行为更符合“夜间做梦整理白天记忆”的语义
- 降低白天高峰期资源竞争

## 整体流程

### Phase A: Dream Planner

当用户在某一天产生足够多的有效对话后，系统为该作用域创建次日 dream 计划。

触发时机建议：

- 每轮 turn digest 落盘后
- 检查当前 `(agent_id, channel, user_id, local_date)` 是否已存在 dream 计划
- 若不存在，且达到最小活跃阈值，则生成一个 one-off dream job 写入 `CRON.json`

最小活跃阈值建议：

- `min_digest_count >= 3`
- 或 `total_digest_chars >= 300`

### Phase B: Dream Runner

在计划时间点到达后，后台任务执行如下步骤：

1. 读取目标作用域在目标日期下的所有 conversation digests
2. 读取当日新产生的 candidate / disputed memories
3. 读取必要的历史记忆作为背景
4. 对当天话题进行聚合和归纳
5. 识别值得长期保存的用户记忆
6. 识别值得复用的 agent lessons
7. 生成 dream report
8. 将结构化产物写回持久层

## 产出分层

### 1. Dream Report

用途：

- 给开发者或维护者 review
- 作为调试、回溯、验收的直接依据

内容建议包含：

- 目标作用域
- 目标日期
- 当天高频话题
- 潜在长期记忆候选
- 可能的冲突项
- agent 学到的服务模式
- 本次整理是否实际写入持久层

### 2. User Long-term Memory

这部分表示“关于用户或当前项目”的相对稳定信息。

适合写入的内容：

- 用户偏好
- 当前长期项目
- 稳定约束
- 已形成的决策
- 连续多天重复出现的重要上下文

第一版建议策略：

- 保守写入
- 推断类结果默认以 `candidate` 为主
- 只有重复出现、证据充分的内容才考虑更高置信度

### 3. Agent Lessons

这部分表示“agent 在服务该用户时学到的经验”，而不是用户事实。

例如：

- 用户讨论架构方案时，偏好先调研再出 phased proposal
- 用户更接受结构化对比和风险提示
- 用户常在 review 后再要求落代码

这类信息不应混入用户 memory ledger，而应独立存储并在后续召回时单独注入 prompt。

## 数据存储设计

建议新增目录：

```text
memory/
├── dream/
│   ├── plans.jsonl
│   ├── runs.jsonl
│   ├── lessons.jsonl
│   └── reports/
│       └── YYYY-MM-DD/
│           └── <scope-key>.md
```

### plans.jsonl

用途：

- 记录 dream 是否已经为某个 scope/date 排程
- 防止重复创建计划

建议字段：

```json
{
  "plan_id": "dream-plan-xxx",
  "agent_id": "main",
  "channel": "wechat",
  "user_id": "u123",
  "target_date": "2026-04-20",
  "scheduled_for": "2026-04-21T04:12:00+08:00",
  "job_id": "dream-u123-2026-04-20",
  "status": "scheduled",
  "created_at": "2026-04-20T22:41:00+08:00"
}
```

### runs.jsonl

用途：

- 记录每次 dream 的实际运行情况
- 便于审计和失败重试

建议字段：

```json
{
  "run_id": "dream-run-xxx",
  "plan_id": "dream-plan-xxx",
  "agent_id": "main",
  "channel": "wechat",
  "user_id": "u123",
  "target_date": "2026-04-20",
  "started_at": "2026-04-21T04:12:03+08:00",
  "finished_at": "2026-04-21T04:12:19+08:00",
  "status": "ok",
  "report_path": "memory/dream/reports/2026-04-20/wechat-u123.md",
  "new_memory_count": 2,
  "new_lesson_count": 1,
  "error": ""
}
```

### lessons.jsonl

用途：

- 存放 agent lessons
- 后续参与检索和 prompt 注入

建议字段：

```json
{
  "lesson_id": "lesson-xxx",
  "agent_id": "main",
  "channel": "wechat",
  "user_id": "u123",
  "scope": "service_pattern",
  "status": "active",
  "summary": "讨论架构方案时优先先做现状梳理再出分阶段方案",
  "value": "当用户讨论系统设计时，先查现状，再给 phased proposal，并明确风险与分期。",
  "confidence": 0.72,
  "importance": 0.78,
  "evidence_refs": ["digest:2026-04-20:1", "digest:2026-04-20:3"],
  "first_seen_at": "2026-04-21T04:12:19+08:00",
  "last_seen_at": "2026-04-21T04:12:19+08:00"
}
```

## 调度策略

### 为什么不用固定 cron

用户需求是：

- 每天夜间
- 在 `03:00-08:00` 之间随机选一个时间

这不适合一个固定的 recurring cron 表达式。更适合的方式是：

- 由 planner 每天为活跃 scope 生成一个次日 one-off job
- 任务执行后自动删除

### Job 生成方式

dream job 继续复用现有 `CRON.json` 机制。

建议 job 结构：

```json
{
  "id": "dream-wechat-u123-2026-04-20",
  "name": "Nightly Dream",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "12 4 21 4 *",
    "tz": "Local"
  },
  "payload": {
    "kind": "agent_turn",
    "message": "[dream] consolidate memories for agent=main channel=wechat user=u123 target_date=2026-04-20"
  },
  "delete_after_run": true
}
```

注意：

- 若沿用现有 `agent_turn` 消息方式，需要明确 dream 指令的专用协议
- 第一版更稳妥的做法是后续新增一个 dream 专用 payload kind，而不是长期复用自由文本 message

## Dream Synthesizer 设计

### 输入

- 目标作用域当天的 digest 列表
- 当天候选 memories
- 当前 confirmed memories
- 可选的近 7 天历史记忆摘要

### 输出

建议统一生成结构化 JSON，再由系统负责落盘和写回：

```json
{
  "topics": [
    {
      "title": "nightly dream 机制设计",
      "summary": "用户在讨论为 trustworthy_assistant 增加夜间记忆整理机制",
      "evidence_count": 4,
      "stability": "high"
    }
  ],
  "user_memories": [
    {
      "content": "用户在持续迭代 trustworthy_assistant 的记忆系统",
      "category": "project",
      "confidence": 0.78,
      "importance": 0.86,
      "reason": "同日多次提及且与长期项目一致"
    }
  ],
  "agent_lessons": [
    {
      "kind": "workflow",
      "content": "讨论架构方案时先梳理现状再给 phased design",
      "confidence": 0.72,
      "importance": 0.78,
      "reason": "用户明确要求先调研再出方案"
    }
  ],
  "conflicts": [],
  "open_questions": [
    "是否允许 future phase 自动把 lesson 注入 prompt"
  ]
}
```

### 第一版归纳方式

第一版不必做复杂算法聚类，可采用：

- 先按 digest 列表直接喂给 LLM
- 要求其输出固定 JSON
- 系统层做 schema 校验
- 非法输出则回退为仅生成 report、不写结构化产物

## 检索与 Prompt 注入

### 用户记忆

用户记忆继续沿用现有：

- `memory ledger`
- `MEMORY.md` managed projection
- `hybrid_search()`

### Agent Lessons

新增一个 lessons 检索层，不直接并入现有 `MemoryRecord`：

- 原因一：语义不同，lesson 不是用户事实
- 原因二：便于在 prompt 中单独展示
- 原因三：后续可以独立做过期、降权和清理

建议 prompt 中新增一段：

```md
### Learned Service Patterns

- 当用户讨论架构方案时，优先先做现状梳理，再给分阶段设计。
- 当用户要求 review before implement 时，先给设计稿，不直接改代码。
```

## 风险控制

### 数据隔离风险

风险：

- 不同用户的 digest 被混在同一次 dream 里

控制：

- 所有 dream 查询必须显式带 `(agent_id, channel, user_id, local_date)`
- 禁止 dream 默认复用 `channel="cron"` 下的 agent-wide digest 聚合逻辑

### 误学习风险

风险：

- 单次随口一提被写成长期偏好

控制：

- 第一版只默认写 `candidate`
- 高敏感类内容不自动入长期记忆
- 跨日重复后再考虑提升 confidence

### 语义污染风险

风险：

- 把“用户事实”和“agent 服务经验”混在一个 ledger

控制：

- 用户记忆与 agent lessons 分层存储
- prompt 注入时也分 section 呈现

### 可解释性风险

风险：

- dream 做了什么难以追踪

控制：

- 每次都生成 dream report
- 每条写入都保留 evidence refs
- runs.jsonl 记录执行结果

## 分期方案

### Phase 1: Dream Report Only

目标：

- 跑通随机排程和按 scope 的夜间整理
- 生成可 review 的 report

范围：

- 新增 planner
- 新增 runner
- 新增 report 落盘
- 不自动写 memory
- 不引入 lessons 检索

适合验证：

- 做梦是否真的能总结出有价值的东西
- 数据隔离是否正确

### Phase 2: Candidate Memory Write-back

目标：

- 将低风险、可解释的用户记忆写入 ledger

范围：

- 仅写 `project / preference / constraint / decision`
- 默认 `candidate`
- 保留 evidence refs

### Phase 3: Agent Lessons

目标：

- 引入独立 lessons store
- 在对话前召回 agent 学到的服务模式

范围：

- 新增 lessons repository
- 新增 lessons search
- prompt builder 增加 `Learned Service Patterns`

### Phase 4: Reinforcement

目标：

- 支持跨日强化和自动升级

范围：

- 对连续多天重复主题提升 confidence / importance
- 支持 candidate 到 confirmed 的自动晋升
- 加入 lesson 衰减和清理策略

## 推荐实现改动点

### 新增模块

- `src/trustworthy_assistant/memory/dream_repository.py`
- `src/trustworthy_assistant/memory/dream_service.py`

### 需要扩展的现有模块

- `memory/service.py`
  - 增加按 `agent_id + channel + user_id + local_date` 精确读取 digest 的接口
  - 增加 dream 相关写回辅助方法
- `runtime/turns.py`
  - 在 digest 落盘后触发 `ensure_dream_plan(...)`
- `runtime/cron.py`
  - 后续可考虑支持 dream 专用 payload kind
- `prompting.py`
  - Phase 3 增加 lessons prompt section

## 建议的最小接口

### DreamRepository

- `append_plan(payload: dict) -> None`
- `load_plans(...) -> list[dict]`
- `append_run(payload: dict) -> None`
- `append_lesson(payload: dict) -> None`
- `load_lessons(...) -> list[dict]`
- `write_report(target_date: str, scope_key: str, content: str) -> str`

### DreamService

- `ensure_plan(agent_id: str, channel: str, user_id: str, local_date: str) -> dict | None`
- `has_enough_activity(agent_id: str, channel: str, user_id: str, local_date: str) -> bool`
- `pick_schedule_time(base_date: str, tz_name: str = "Local") -> datetime`
- `run_once(agent_id: str, channel: str, user_id: str, target_date: str) -> dict`
- `synthesize(...) -> dict`
- `persist_result(...) -> dict`

## 验收标准

### Phase 1 验收

- 活跃用户在某日首次满足阈值后，可自动写入一条次日凌晨 dream job
- dream job 到时可自动执行
- 仅整理对应 `agent_id + channel + user_id + target_date` 的 digest
- 产出一份结构完整的 markdown report
- 执行信息可在 `runs.jsonl` 中追踪

### Phase 2 验收

- dream 可将低风险候选记忆写入 ledger
- 写入内容可通过现有 memory explain 或 trace 追溯
- 不出现跨用户串味

### Phase 3 验收

- lessons 可被检索
- 新对话中能稳定注入相关 learned service patterns
- lessons 不污染用户事实型记忆

## 待确认决策

- 第一版是否只生成 report，不做任何自动写回
- dream 是否允许为终端本地用户也默认启用
- agent lessons 是否仅做 per-user 学习，还是未来支持更高层级的通用学习
- 是否需要提供开关，让某些 channel/user 禁用 dream
- 是否需要增加 `/dream status` 或 `/dream report` 之类的观察命令

## 推荐落地顺序

1. 先补齐按 scope 精确读取 digest 的 API
2. 实现 dream repository 和 report-only runner
3. 接入 planner，自动为活跃 scope 生成次日 one-off job
4. 完成 Phase 1 验证后，再加 candidate memory write-back
5. 最后再做 lessons store 与 prompt 注入

## 结论

`Nightly Dream` 最适合做成一个复用现有 `cron + memory` 基础设施的夜间后台整理层，而不是另起一套独立 agent runtime。

第一版最稳妥的路线是：

- 按用户作用域隔离
- 每天随机一次夜间整理
- 先产出 report
- 再逐步开放 candidate memory 和 agent lessons

这样既能实现“随着用户使用，agent 主动进化”，又能把误学习、串味和不可解释性控制在可接受范围内。
