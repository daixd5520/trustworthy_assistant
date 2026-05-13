# 启动上下文

这个文件提供智能体启动时加载的附加上下文。

## 项目上下文

这个智能体配置了一个可信记忆系统，用于持续跟踪事实、偏好和上下文。`workspace` 目录中包含一组会影响智能体行为的配置文件：

- SOUL.md：人格与沟通风格
- IDENTITY.md：角色定义与边界
- TOOLS.md：可用工具与使用指南
- MEMORY.md：长期事实与偏好
- HEARTBEAT.md：主动行为说明
- BOOTSTRAP.md：当前文件，提供额外启动上下文
- AGENTS.md：多智能体协作说明
- USER.md：用户上下文与偏好

## 工作区结构

```
workspace/
  *.md          -- 启动配置文件（加载到 system prompt 中）
  CRON.json     -- 定时任务定义
  memory/       -- 每日记忆日志
  skills/       -- 技能定义
  .sessions/    -- 会话记录（自动管理）
  .agents/      -- 每个智能体的状态（自动管理）
```
