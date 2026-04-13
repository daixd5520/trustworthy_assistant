# Debug Session

- Status: [CLOSED]
- Started At: 2026-04-13
- Scope:
  - 微信文本发送偶发 `sendMessage ret=-2`
  - 微信文件发送失败
- Symptoms:
  - 终端报错栈显示在 `wechat.py::_send_text_sequence()` 调用 `send_text()` 时抛出 `RuntimeError: sendMessage ret=-2 errcode=None errmsg=None`
  - 用户反馈文件仍然无法发送到微信
- Guardrails:
  - 在拿到运行时证据前，不修改业务逻辑
  - 第一处代码变更仅用于埋点和证据收集

## Hypotheses

1. 文本分段发送引入了节奏/上下文问题，第二条或后续消息使用同一个 `context_token` 被服务端拒绝，导致 `ret=-2`。
2. `context_token` 在接收消息后可用于首条回复，但在多条发送或较长处理后已经失效，文件发送同样因为 token 失效而失败。
3. 文件发送链路不是单纯“发送失败”，而是前置 CDN 上传、媒体类型分类、或调用发送 API 的某一段返回了错误，只是当前日志不足以区分。
4. 文本发送和文件发送共享了同一账号/会话状态问题，例如 `typing_ticket`、账号 token、to_user_id 或上下文绑定不稳定，导致两类发送都受影响。
5. 文件其实已经上传成功，但最终发送接口要求的参数格式与 `send_text` 不同，当前代码没有记录关键响应字段，所以表面看起来像“发不到微信”。

## Evidence Plan

- 给文本发送、文件上传、文件发送、context_token 解析增加最小埋点
- 记录每次发送的分片序号、长度、目标用户、是否有 context_token、接口返回值
- 记录文件发送的媒体类型、文件大小、上传结果摘要与最终发送结果
- 复现一次文本回复失败与文件发送失败，对照日志排除/确认上述假设

## Resolution

- 文本发送崩溃根因：微信 `sendMessage` 失败时异常未被上层接住，会直接打断 bot 主循环。
- 文件发送根因一：`getuploadurl` 新返回格式包含 `upload_full_url`，而旧代码只识别 `upload_param`。
- 文件发送根因二：实际运行的 `/Users/bytedance/Documents/trae/nanobot/.venv` 缺少 `cryptography`，导致文件加密上传链路无法执行。
- Fix:
  - 兼容 `upload_full_url` 与旧 `upload_param` 两种上传目标格式
  - 文本发送失败改为受控记录，不再直接打崩 bot 进程
  - 在实际运行环境中安装 `cryptography`
- Verification:
  - 用户确认文件已恢复发送

## Follow-up Session

- Status: [OPEN]
- Started At: 2026-04-14
- Scope:
  - `read_image` 在当前 MiniMax M2.7 接入下无法识别图片
- Symptoms:
  - 用户反馈 MiniMax M2.7 理论上支持图片，但当前实现会回“没看到任何图片”或走不到正确视觉分支
- Hypotheses:
  1. 当前 `read_image` 的后端选择逻辑直接绕开了 MiniMax，导致根本没有尝试视觉请求。
  2. MiniMax 兼容端点支持图片，但要求的请求格式和现有 `Anthropic` / `OpenAI` 兼容格式不同。
  3. 实际配置里的 `MODEL_ID` 已经是 `MiniMax-M2.7`，但代码没有像 openclaw 那样识别它属于可看图模型。
  4. 图片下载链路偶发失败，导致上层误判成“模型没看到图”，其实是工具没有拿到图片文件。
  5. 本机并行 bot 实例或旧进程回包仍然干扰了本轮结论。

## Evidence Plan

- 记录 `read_image` 实际选择了哪条后端分支、采用了什么模型名
- 记录图片本地路径、媒体类型与文件大小，确认工具拿到的是有效图片
- 记录 MiniMax 视觉调用的请求模式与错误摘要
- 对照用户提供的线索，确认是否需要兼容 `MiniMax-M2.7` / `MiniMax-M2.7-highspeed`

---

# Debug Session

- Status: [OPEN]
- Started At: 2026-04-14
- Scope:
  - 微信引用消息场景下，bot 回答内容疑似重复
- Symptoms:
  - 用户反馈“引用类问题似乎会重复回答，会输出两句一样意思的话”
- Guardrails:
  - 在拿到运行时证据前，不修改业务逻辑
  - 第一处代码变更仅用于埋点和证据收集

## Hypotheses

1. 引用消息被组装成 `引用内容 + 当前消息` 两段强提示，模型分别对两段作答，形成同义重复。
2. 微信引用消息在当前链路里被处理了两次，导致两次相近回复都被发出去。
3. 进度播报与最终回复在引用场景下语义过近，用户感知为“重复回答”。
4. `_split_text_for_delivery()` 的分段策略把一条带引用上下文的回答切成两段近义话，显得像重复。
5. `turn_input` 或 session 中存在重复注入，导致模型上下文里同一个引用问题出现两次。

## Evidence Plan

- 记录引用消息的 `turn_input` 组装结果、图片/引用元数据与去重键
- 记录一次 turn 内是否触发了 progress reply 与 final reply，以及两者的文本摘要
- 记录最终发送前的分段结果，确认是否是切分造成“近义双句”
- 复现一次引用消息，基于日志判断是“模型生成重复”还是“发送链路重复”
