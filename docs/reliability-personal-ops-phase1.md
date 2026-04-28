# Reliability + Personal Ops Phase 1

## 背景

本阶段目标是先为两个方向建立最小可用能力：

- Reliability Layer：让通道在短时网络失败时降级，而不是直接退出
- Personal Ops Agent：让 assistant 能记录和展示最基本的 pending commitments

实现遵循 TDD：

1. 先写失败测试
2. 运行并确认失败
3. 实现最小代码让测试通过
4. 跑更广回归测试，确认没有回归

## Phase 1 已实现

### Reliability

- 微信 `get_updates()` 在 `ConnectTimeout` / `ReadTimeout` 时返回降级结果，而不是抛出异常
- `WeChatBotRunner` 增加最小 poll health 状态
- 当轮询结果携带 `error` 时：
  - 增加连续失败计数
  - 进入 `degraded` 状态
  - 输出带 backoff 的日志
  - 在空消息时按 backoff sleep，再继续轮询

### Personal Ops

- 新增 `PersonalOpsService`
- 以 `ops/commitments.jsonl` 作为 append-only 持久层
- 支持：
  - `add_commitment()`
  - `list_commitments()`
  - `complete_commitment()`
  - `format_pending_context()`
  - `set_due_at()`
  - `block_commitment()`
  - `dismiss_commitment()`
  - `expire_overdue_commitments()`

当前 commitment 状态包括：

- `pending`
- `completed`
- `blocked`
- `dismissed`
- `expired`

### Prompt / Runtime 接入

- `PromptBuilder.build()` 新增 `ops_context`
- `TurnProcessor` 新增 `build_ops_context()`
- 正常 turn prompt 中可展示 `Pending Commitments`

### 命令面

- 微信 slash command 已支持：
  - `/ops list`
  - `/ops add <title>`
  - `/ops done <commitment_id>`
  - `/ops due <commitment_id> <due_at>`
  - `/ops block <commitment_id> [reason]`
  - `/ops dismiss <commitment_id> [reason]`
  - `/ops extract <natural language text>`
- CLI 已支持：
  - `/ops list`
  - `/ops add <title>`
  - `/ops done <commitment_id>`
  - `/ops due <commitment_id> <due_at>`
  - `/ops block <commitment_id> [reason]`
  - `/ops dismiss <commitment_id> [reason]`
  - `/ops extract <natural language text>`

## 当前限制

- 只覆盖了微信通道的最小降级逻辑，尚未统一到其他通道
- 还没有全局 runtime health dashboard
- 还没有 heartbeat / cron 对 pending commitments 做主动巡检
- 还没有做去重、优先级、阻塞依赖、due date 策略
- `commitments.jsonl` 目前没有文件锁，多进程并发写入仍需后续增强
- 自然语言 `ops` 当前只支持提议式提取，不会自动写入

## Ops Extractor

- `ops-extractor` skill 位于 `workspace/skills/ops-extractor/SKILL.md`
- 当前接入方式是显式命令：
  - `/ops extract <natural language text>`
- 返回的是 candidate commitment
- 默认策略是：
  - 先提取
  - 再展示建议
  - 不直接写入 `ops`

## 下一阶段建议

### Reliability

- 扩展到 WeCom 和其他外部依赖
- 抽象统一 `channel health` 结构
- 增加退避上限、恢复日志和观测命令

### Personal Ops

- 增加更多状态：`blocked / dismissed / expired`
- 接入 reminder / cron / heartbeat 巡检
- 支持从对话或 dream 中自动提炼候选 commitment
- 支持 due date、source evidence、priority

## 验证

本阶段新增和回归测试均已通过：

```bash
python3.11 -m unittest discover -s tests -q
```
