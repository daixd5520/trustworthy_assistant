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

- Status: [RESOLVED]
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

## Latest Evidence

- 现有 `trae-debug-log-vision-read-image.ndjson` 只有一组 `pre-fix` 记录，仍显示 `request_mode = openai-chat-completions-image_url-data-uri`。
- 目前还没有任何证据表明用户本轮“还是不行”对应的是修改后的 `inline-base64-text` 分支。
- 下一步需要补充最小埋点，明确记录当前代码版本标记、请求模式，以及是否命中新的 MiniMax 分支，然后要求用户在重启 bot 后复现一次。
- 官方 `OpenAI API 兼容` 页面仅列出 `MiniMax-M2.7/M2.5/M2.1/M2` 等文本模型，不包含 `MiniMax-VL-01`；官方 `Anthropic API 兼容` 页面还明确说明 `messages` 不支持 `image` 输入。
- 运行时直连验证结果：
  - `MiniMax-M2.7 + image_url` 返回 200，但正文明确说“没有看到图片”。
  - `MiniMax-VL-01 + image_url` 使用当前 key 返回 400：`unknown model 'MiniMax-VL-01'`。
- 结论：当前这把 key/模型权限下，不能把 `MiniMax-M2.7` 当成视觉模型；要实现看图，必须走独立视觉模型配置，并提供对 `MiniMax-VL-01` 可见的 key。
- 新证据：通过官方 `mmx` CLI 路线，使用同一把 `.env` 中的 key 可以成功执行 `vision describe`。
- 已实现最小修复：`read_image` 对 MiniMax 相关配置优先调用 `python3 .dbg/mmx_from_env.py vision describe ...`，并在本地直接调用 `ToolRegistry.read_image()` 验证成功，返回正常中文图片描述。
- 新证据（微信播报异常）：
  - `wechat.py:_build_turn_input` 会把 `图片 N 本地路径：/Users/...jpg` 写进 turn_input。
  - `runtime/turns.py:ProgressTracker._subject_hint()` 会优先从 user_input 中匹配路径。
  - 实际发送日志已证明首条进度播报被拼成 `我先把/Users/...jpg的脉络捋一下。`
- 最小修复方向：保留图片本地路径给工具使用，但在进度播报阶段对图片路径做语义化降级，不再向用户暴露本地文件路径。
- 新证据（最终回复未切分）：
  - `wechat.py:run_forever` 在发送最终回复时固定调用 `_send_text_sequence(..., allow_split=False)`。
  - `_split_text_for_delivery()` 本身具备按句号、段落拆分短消息的能力，但被上述固定参数绕过。
- 最小修复方向：保留 `_split_text_for_delivery()` 现有规则，只把最终回复发送改为 `allow_split=True`，让微信端按短句拆成多条自然消息。
- 用户最终确认：线上 bot 已恢复正常识图。

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

---

# Debug Session

- Status: [OPEN]
- Started At: 2026-04-14
- Scope:
  - 微信发送文件后可见但无法下载/预览
  - 用户发送图片后本地显示文件存在，但上层无法解析图片内容
- Symptoms:
  - 用户反馈发送出去的文件在微信里“能看到文件”，但不能下载，也不能预览
  - 用户发送图片后，系统提示文件已存在，但无法解析内容
- Guardrails:
  - 在拿到运行时证据前，不修改业务逻辑
  - 第一处代码变更仅用于埋点和证据收集

## Hypotheses

1. `send_file()` 构造的 `file_item` 字段缺少微信客户端下载/预览所需的关键元数据，导致消息可见但附件不可用。
2. 入站图片的 `encrypt_query_param` 或 AES key 提取字段不完整，当前代码下载或解密出的字节流不是原图，所以本地虽有文件但内容损坏。
3. 微信入站图片与出站文件的 CDN 协议格式存在差异，当前 `download_cdn_media()` / 解密逻辑不能直接复用到实际收到的图片。
4. 图片落地文件的后缀、MIME 或文件头判断错误，导致上层 `read_image` 没有把它当成可读图片。
5. 当前运行中的 bot 不是最新代码，或运行环境依赖/配置与仓库不一致，导致现象和代码阅读结果不一致。

## Evidence Plan

- 检查现有 `.dbg` 日志与本地落地图像文件头，确认图片是“下载失败”“解密失败”还是“落地后识别失败”
- 检查当前 `file_item` / `image_item` 负载与历史埋点，确认发送链路是否缺字段或字段格式不对
- 如现有证据不够，只补最小埋点到入站图片提取、下载解密、出站文件发送三处
- 复现一次“发文件”和“一张图片给 bot”，对照 pre-fix 日志后再决定最小修复

## Latest Follow-up

- 2026-04-14
- 新症状：
  - bot 发出的文件在微信里可见，但 PC 与手机端都无法完成预览或下载，进度总卡在最后
- 本轮待确认点：
  1. 发送链路里 `getuploadurl -> CDN upload -> sendmessage(file_item)` 三段是否都返回了可用字段
  2. 最终 `file_item` 的 `media` / `filekey` / `download_encrypted_query_param` / 大小字段是否与微信客户端下载预期一致
  3. 当前运行账号与最新登录账号是否一致，避免把旧账号状态误当成文件协议问题
