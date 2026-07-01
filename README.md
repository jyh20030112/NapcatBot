# NapCatQQ Agent

基于 NapCatQQ / OneBot v11 的群聊 Agent。LLM 与 function calling 由
`/Users/jyh030112/Desktop/Dev/SimAgentPlg` 提供，本项目只负责 NapCat
适配、群聊上下文、话题状态和 QQ 动作工具。

## 运行

```bash
uv sync
cp .env.example .env
uv run python -m app.main
```

WebSocket 采用线上 `NapcatBot` 一样的反向连接方式：本项目监听
`NAPCAT_WS_HOST:NAPCAT_WS_PORT`，NapCat 里填
`ws://host.docker.internal:8082`。

`.env` 中的 `BASE_MODEL`、`MODEL_API_KEY` 和 `MODEL_URL` 会传给
`simagentplg.ModelConfig.from_env()`。

## 动作工具

所有对 QQ 的出站动作都通过 SimAgentPlg 的 function call 执行：

- `skip_reply`: 本轮不回复
- `send_msg`: 在当前群发送普通文本
- `send_at_msg`: 在当前群 @ 指定成员并发送文本

后续新增动作时，在 `app/llm/napcat_actions.py` 里追加 tool schema 和
对应的 `do_<tool_name>()` 方法即可。
