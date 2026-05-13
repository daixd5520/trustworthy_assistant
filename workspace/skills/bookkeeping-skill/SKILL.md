---
name: 记账助手
description: 记录收支、生成账本统计、配置日报周报月报。用户提到消费、收入、报销、账单、统计或定时推送时调用。
invocation: bookkeeping-skill
---

# 记账助手

这个技能用于把日常收支记入本地账本，并在用户需要时生成统计报表或配置自动推送。

## 什么时候用

- 用户在描述一笔消费或收入
- 用户说“帮我记一笔”“记账”“入账”“报销到了”“今天花了多少钱”
- 用户要看今日、本周、本月、上周、上月账本
- 用户要看分类统计、支出结构、净收支
- 用户要开启每天、每周、每月自动账单推送

## 优先工具

### 1. `ledger_add_entry`

在下面这些场景优先调用：

- 明确出现了金额和消费/收入行为
- 用户要求“记下来”“记一笔”
- 用户在补录账目

字段建议：

- `entry_type`: `expense` 或 `income`
- `amount`: 正数
- `category`: 尽量简洁稳定，如 `food`、`transport`、`shopping`、`salary`、`rent`
- `note`: 商户、场景、备注
- `account`: 如 `wechat`、`alipay`、`cash`、`bank_card`
- `source`: 如 `wechat`、`manual`、`reimbursement`

### 2. `ledger_report`

在下面这些场景优先调用：

- 用户要“今天账本”“本周账本”“本月账单”
- 用户要“统计一下”“看支出分类”“看收入支出汇总”

可用周期：

- `today`
- `yesterday`
- `week`
- `last_week`
- `month`
- `last_month`

### 3. `ledger_configure_reports`

在下面这些场景优先调用：

- 用户要“每天晚上 11 点发我账本”
- 用户要“每周给我发周报”
- 用户要“每月发月账单”

默认策略：

- 日报：`23:00`
- 周报：周日 `23:00`
- 月报：每月 1 日 `00:05` 发送上月账单

## 分类建议

- 餐饮：`food`
- 交通：`transport`
- 购物：`shopping`
- 房租：`rent`
- 水电网：`utilities`
- 娱乐：`entertainment`
- 医疗：`medical`
- 工资：`salary`
- 奖金：`bonus`
- 报销：`reimbursement`
- 转账/红包收入：`transfer_income`
- 转账/红包支出：`transfer_expense`

## 回答原则

- 记账成功后，先确认记了什么，不要复读参数
- 查账时先给结论和统计，再补关键明细
- 默认金额单位按用户上下文理解；没有特别说明时优先按 `CNY`
- 如果用户信息不够，先补最少的问题，比如“这是支出还是收入？”

## 示例

用户：“午饭 32，帮我记一下。”

处理：

- 调用 `ledger_add_entry(amount=32, category="food", entry_type="expense", note="午饭")`
- 回复“记好了，今天新增一笔餐饮支出 32 元。”

用户：“看看这周花了多少钱，按类别分一下。”

处理：

- 调用 `ledger_report(period="week")`
- 先给总支出，再给分类统计和关键明细

用户：“以后每天晚上 11 点、每周末、每月给我发账单。”

处理：

- 调用 `ledger_configure_reports(daily_enabled=true, weekly_enabled=true, monthly_enabled=true, daily_time="23:00", weekly_time="23:00", weekly_weekday="sun")`
- 回复已开启，并说明月报默认在每月 1 日发送上月账单
