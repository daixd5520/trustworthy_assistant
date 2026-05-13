# 常青记忆

> 这个文件用于存储不会每天变化的长期事实与偏好。
> 智能体会在每次会话开始时读取它，以获得上下文。

## 用户偏好

- 用户希望你叫她：主人
- 偏好：简洁回答，而不是冗长解释
- 时区：UTC+8
- 主要语言：中文，熟悉英文技术术语

## 重要上下文

- 用户正在做一个 AI 智能体项目
- 用户对系统架构感兴趣
- 用户是一个专业的 AI 研究人员，在吉林大学读硕士，专业是计算机科学与技术
- 用户是孙燕姿铁粉，希望在非严肃情境下可以提及孙燕姿相关资讯

<!-- ledger-memory:start -->
## Ledger Memory View

> This section is managed automatically from the structured memory ledger.
> Edit the ledger via the assistant workflow instead of changing this block by hand.

## Preferences

- 用户写代码之前，要先给思路性伪代码，再写实际代码。不要直接给代码。 [preference.preference]
- 用户发食物图片时，自动记录到 workspace/food-log/YYYY-MM-DD.md，包括：内容、热量估算（约几 kcal）、来源、备注。热量的 skill 已经可以估算，下次直接估算后写入文件。 [preference.preference]
- 用户不喜欢命令式表达，希望我懂她话里隐含的意思，用自然轻松的方式回应，而不是生硬的提醒或指令。比如她说"想玩五分钟手机"是想休息，我应该自然地说"去吧"而不是"催你干活" [preference.preference]
- 用户希望每天晚上有当日聊天摘要推送，这已经通过 HEARTBEAT 机制实现（晚上10:30之后自动发送） [preference.preference]
- 用户问算法题时，优先使用 C++ 解答 [preference.preference]
- 用户最喜欢孙燕姿的歌是《银泰》 [preference.preference]

## Facts

- workspace 目录路径是 /Users/bytedance/Documents/trae/trustworthy_assistant/workspace，里面有 memory/（含 daily、ledger、review）、skills/、CRON.json 等配置文件 [fact.general]
- style-clone skill 已创建，用于持续学习用户的说话风格（简洁、短句、自然、不喜欢命令式），已记录今日观察到的一些风格特征 [fact.general]
- personal-assistant skill 已支持隐式提醒意图识别：关键词包括"先这样""先玩了""先休息一下""先走一步"以及"玩X分钟手机""休息X分钟"等，会自动提取时间并设置cron提醒 [fact.general]
- 用户有ADHD（注意力缺陷多动障碍） [fact.general]

## Context

- 生日礼物记录：- 秦莉玲 4.29 生日礼物已买：迈从 g87v2 键盘，238.85元- 王加贝 4.29 生日礼物已买：哈根达斯冰淇淋，118元- 胥心 4.30 生日礼物已买：也是买键盘 [context.general]
- 生日礼物记录：
- 秦莉玲 4.29 生日礼物已买：迈从 g87v2 键盘，238.85元
- 王加贝 4.29 生日礼物已买：哈根达斯冰淇淋，118元
- 胥心 4.30 生日礼物待买：也是买键盘 [context.general]
- 用户桌面有一个重要文件：BMS-CBIO-2025-414-20260401.docx，大小约4MB [context.general]

<!-- ledger-memory:end -->
