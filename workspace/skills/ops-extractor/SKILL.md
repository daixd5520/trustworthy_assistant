---
name: "ops-extractor"
description: "Extracts candidate commitments from natural language. Invoke when user expresses reminders, follow-ups, pending tasks, or future actions that may belong in Personal Ops."
---

# Ops Extractor

## Purpose

This skill extracts candidate commitments for `Personal Ops` from ordinary user messages.

Use it when the user appears to be expressing:

- a reminder
- a follow-up task
- a future action
- a pending decision
- a commitment that should be tracked later

This skill is intentionally conservative:

- It should prefer proposing candidate ops over silently creating them
- It should avoid turning casual remarks into commitments
- It should separate "facts to remember" from "things to do"

## When To Invoke

Invoke this skill when the latest user message includes signals such as:

- "提醒我..."
- "记得..."
- "之后帮我..."
- "回头处理..."
- "先记一下..."
- "下次继续..."
- "帮我跟进..."
- "明天/下周/之后做..."

Do not invoke it for:

- pure factual statements
- stable preferences
- project background with no actionable follow-up
- generic brainstorming with no intended follow-up

## Output Goal

This skill should produce `candidate commitments`, not direct writes.

Preferred output shape:

```json
{
  "should_create_ops": true,
  "items": [
    {
      "title": "明天检查 cron 健康状态",
      "detail": "用户希望后续检查 cron 是否正常运行",
      "due_hint": "tomorrow",
      "reason": "用户明确表达了提醒/后续跟进需求",
      "confidence": 0.86
    }
  ]
}
```

If nothing actionable is detected:

```json
{
  "should_create_ops": false,
  "items": []
}
```

## Extraction Rules

### 1. Prefer actions over facts

Good candidates:

- "明天提醒我看一下账单推送有没有问题"
- "回头帮我检查 wecom 通道的重试策略"
- "下周继续做 Personal Ops 的 dashboard"

Not good candidates:

- "我现在在做 Personal Ops Agent"
- "我偏好中文回答"
- "这个项目最近在调 dream"

### 2. Keep titles short and actionable

Title guidelines:

- concise
- verb-oriented when possible
- one commitment per title

Good:

- `检查 cron 健康状态`
- `补 wecom 重试策略`
- `继续做 ops dashboard`

Avoid:

- very long titles
- merged multi-action titles
- vague titles like `处理一下这个`

### 3. Put nuance into `detail`

Use `detail` for:

- blockers
- context
- references
- extra constraints

### 4. Be conservative with due dates

If the user gives an explicit time:

- preserve it as `due_hint`

Examples:

- `明天`
- `下周一`
- `今晚`
- `月底前`
- `2026-05-03 20:00`

Do not fabricate precise timestamps if the user did not give one.

### 5. Separate candidate ops from memory

If the message is mostly a fact, preference, or project background:

- it may belong to `memory`
- it should not become an `ops` candidate unless a future action is clearly implied

## Confirmation Strategy

Default behavior should be:

1. Extract candidate ops
2. Show a compact proposal
3. Ask for confirmation before writing

Suggested UX:

```text
我识别到一个可跟进事项：
- 明天检查 cron 健康状态

如需加入 ops，请回复“加入”或使用 /ops add。
```

Only consider silent auto-write when:

- confidence is very high
- wording is explicit
- product policy allows it

## Adversarial Checklist

Before returning a candidate, challenge it:

- Is this really an action, not a fact?
- Is the title concrete enough?
- Did the user actually imply follow-up?
- Could this be a casual thought rather than a commitment?
- Would auto-creating this annoy the user?

If uncertain, return no candidate or ask for confirmation.

## Examples

### Example A

Input:

```text
明天提醒我看一下 cron 有没有失败任务。
```

Output:

```json
{
  "should_create_ops": true,
  "items": [
    {
      "title": "检查 cron 失败任务",
      "detail": "用户希望明天检查 cron 是否存在失败任务",
      "due_hint": "tomorrow",
      "reason": "明确提醒请求",
      "confidence": 0.91
    }
  ]
}
```

### Example B

Input:

```text
我最近在做 Personal Ops Agent。
```

Output:

```json
{
  "should_create_ops": false,
  "items": []
}
```

### Example C

Input:

```text
回头把 wecom 的网络重试也补上，等我先把微信这边看稳。
```

Output:

```json
{
  "should_create_ops": true,
  "items": [
    {
      "title": "补 wecom 网络重试",
      "detail": "当前前置条件是先确认微信通道稳定",
      "due_hint": "",
      "reason": "明确的后续实现动作",
      "confidence": 0.82
    }
  ]
}
```

## Implementation Notes

For `trustworthy_assistant`, this skill should ideally integrate with:

- `PersonalOpsService` for eventual write
- slash/CLI confirmation flows
- future heartbeat review
- future dream-to-ops candidate extraction

The recommended first production behavior is:

- detect
- propose
- confirm
- then write

Not:

- detect
- auto-write immediately
