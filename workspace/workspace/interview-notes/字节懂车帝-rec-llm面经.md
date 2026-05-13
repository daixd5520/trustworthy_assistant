# 字节懂车帝 - Rec LLM 面经汇总

> 来源：用户简历定制面试追问树
> 日期：2026-04-15

---

## 核心攻击路径

三个主线：
1. 懂车帝 AI搜索链路 + 结构化检索（主线，70% 时间）
2. RAG / 检索排序（次主线）
3. SFT / 数据策略（科研 + 工业结合点）

---

## 一、懂车帝 AI搜索（最核心）

你写的是：意图识别 → 约束结构化 → 车型召回 → LLM回复

### 🔥 1. 结构化 Query

**你写的**：把 Query 转成 XML schema

**会被问**：
- schema 是固定字段还是动态扩展？
- 一个 query 能映射多个 constraint 吗？
- constraint 之间是 AND / OR 还是有权重？

**本质**：语义 → 可执行查询语言的映射设计

**继续追**：
- LLM 是怎么保证生成合法 XML 的？
- 有没有 CFG / constrained decoding？
- 有没有 post-check？
- 错了是 regenerate 还是 repair？

**你写的**：多阶段校验降低幻觉风险

**会被问**：
- 具体几阶段？每一阶段在干嘛？

---

### 🔥 2. 幻觉控制（亮点也易追死）

**会被问**：
- hallucination 在你这个任务里具体指什么？
  - 生成不存在车型？参数错？约束冲突？
- 你是用训练解决，还是用系统设计解决？
  - 哪些是 SFT 解决的？
  - 哪些是 rule / system constraint？

---

### 🔥 3. 58% → 98%（Hard case negative sampling）

**会被问**：
- hard case 怎么定义？基于模型 loss 还是人工规则？online mining 还是 offline？
- 为什么 hard negative 有用？
  - 正确方向：decision boundary 附近样本 density 提升 → margin 学得更清晰
- 有没有过拟合风险？

---

### 🔥 4. P90 91ms（工程能力核验）

**会被问**：
- 每个模块 latency breakdown 是多少？
- LLM inference 占多少？
- 有没有做 caching / batching / vLLM？
- 如果说不清 → 直接判定没参与真实系统

---

## 二、RAG 系统（UCloud）

### 🔥 1. BGE + Milvus + reranker

**会被问**：
- embedding 是怎么训练的？
- cosine similarity 为什么能 work？
- "语义相似"→ embedding space 是怎么形成语义结构的？

### 🔥 2. reranker

**关键问题**：
- reranker 输入是什么？pair 还是 list？
- loss 是 pointwise / pairwise / listwise？

### 🔥 3. 提升 9.5%

**会被问**：
- baseline 是什么？
- evaluation dataset 怎么来的？

---

## 三、RICO 动态推理路由（隐藏王牌）

### 🔥 1. 路由策略

**你写的**：基于置信度 / margin / 熵

**会被问**：
- 为什么选这三个？
- 数学定义是什么？
  - entropy = -∑p log p
  - margin = top1 - top2

### 🔥 2. 决策本质

**关键问题**：你这个 routing 本质是在优化什么？

**正确答案**：expected compute vs accuracy trade-off

### 🔥 3. CoT 蒸馏

**会被问**：
- teacher 是谁？
- student 学的是 reasoning 还是答案？
- process supervision vs outcome supervision

---

## 四、SFT / 数据

### 🔥 1. Hard sample mining

**会被问**：
- 为什么难样本更重要？
- easy sample 会不会有用？

**核心**：gradient contribution 分布不均

### 🔥 2. ∆S

**会被问**：
- reward model 的 scale 稳定吗？
- 不同模型之间可比吗？（考 calibration）

### 🔥 3. SimSFT

**会被问**：
- instruction ↔ response 交换为什么成立？
- 会不会破坏语义？
- 如果答不上 → 被认为是"trick 方法"

---

## 五、最大风险点

面试官会不断试图把你往 **"你是不是只是在调 prompt / 拼 pipeline？"** 这个方向上压。

**必须持续强调三件事**：
1. 建模假设（为什么这样建）
2. 数据分布（你在优化什么分布）
3. 系统约束（latency / schema / retrieval space）

---

## 六、真实面试 Closing 问题

> 如果让你把现在这个 AI搜索系统 completely 用一个大模型 end-to-end 做掉，你怎么设计？

**本质**：考你有没有理解 modular system 为什么存在

---

## 准备建议

每次回答必须：
- ✅ 说清建模假设
- ✅ 说清数据分布
- ✅ 说清系统约束
- ❌ 不要只说"调 prompt"或"拼 pipeline"