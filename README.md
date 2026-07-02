# NapcatBot

基于 NapCatQQ / OneBot v11 的 QQ 群聊 Agent。LLM 调用与 function calling 由
[SimAgentPlg](https://github.com/jiangyiheng15/SimAgentPlg) 提供，本项目负责
NapCat 适配、群聊状态管理、话题追踪和 QQ 动作工具。

## 架构

```
QQ 群消息 → NapCatQQ → WebSocket → NapcatWebSocketAdapter
                                        │
                                   GroupMessageHandler
                                   ┌──────┼──────┐
                                   │      │      │
                          TopicAgentService  │  NapcatReplyAgent
                          (话题归类+摘要)     │  (执行回复动作)
                                         │
                                    DecisionService
                                    (回复意图决策)
                                         │
                                    post_check_decision
                                    (硬规则二次校验)
```

三条独立的 Agent 管线：

| Agent | 职责 | 工具 |
|---|---|---|
| **TopicAgentService** | 将消息归类到话题，后台异步生成话题摘要 | `list_recent_topics`, `get_topic_messages`, `create_topic`, `assign_message_to_topic` |
| **DecisionService** | 判断该不该回复、以什么方式回复 | 无工具，直接输出结构化 JSON |
| **NapcatReplyAgent** | 根据决策结果执行 QQ 动作 | `skip_reply`, `send_msg`, `send_at_msg` |

## 项目结构

```
NapcatBot/
├── main.py                          # 入口，WebSocket 监听 + env 热重载
├── app/
│   ├── config.py                    # 环境变量读取（Settings）
│   ├── adapters/
│   │   └── napcat_ws.py             # WebSocket Server，接收 OneBot 事件
│   ├── core/
│   │   ├── message.py               # BotMessage 结构 + NapCat 原始事件解析
│   │   ├── group_state.py           # GroupState / TopicState 运行时状态
│   │   ├── reply.py                 # ReplyDecision 类型 + detect_risk + clean_reply
│   │   ├── decision_postcheck.py    # LLM 决策后的硬规则二次校验
│   │   ├── context_builder.py       # 为三个 Agent 构建 prompt/task
│   │   ├── topic_store.py           # SQLite 持久化（topics + messages）
│   │   └── json_logging.py          # 结构化 JSON 日志
│   ├── handlers/
│   │   └── group_message_handler.py # 消息处理主流程
│   ├── llms_tools/
│   │   ├── napcat_action_tools.py   # QQ 动作工具（skip_reply/send_msg/send_at_msg）
│   │   └── napcat_topic_tools.py    # 话题管理工具
│   └── services/
│       ├── topic_agent_service.py   # 话题归类 + 后台摘要生成
│       ├── decision_agent_service.py# 回复意图决策
│       └── reply_agent_service.py   # 回复动作执行
└── data/
    └── topics.sqlite3               # 话题和消息持久化（自动创建）
```

## 快速开始

### 1. 环境配置

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# NapCat WebSocket 连接（本项目监听，NapCat 反向连接）
NAPCAT_WS_HOST=0.0.0.0
NAPCAT_WS_PORT=8082

# 机器人 QQ 号与昵称
BOT_ID=123456789
BOT_NAME=蛋总

# 干运行模式：HIDE=1 时只观察不发送消息
HIDE=0

# LLM 配置（传给 simagentplg.ModelConfig.from_env()）
BASE_MODEL=deepseek-v4-flash
MODEL_API_KEY=sk-xxxxxxxx
MODEL_URL=https://api.deepseek.com
LLM_TIMEOUT=60
LLM_TEMPERATURE=0.2
```

### 2. 安装运行

```bash
uv sync
uv run python main.py
```

### 3. NapCat 配置

在 NapCat 中添加反向 WebSocket 连接：

```
ws://host.docker.internal:8082
```

（如果 NapCat 和本项目在同一台机器，用 `ws://127.0.0.1:8082`）

## 功能特性

### 话题追踪

- LLM 驱动的消息话题归类（`TopicAgentService`）
- 支持通过 `reply` 继承原消息的话题
- 话题摘要自动生成：首次归类后，后台异步调用 LLM 将聊天记录总结为可读摘要
- SQLite 持久化，重启不丢失

### 回复决策

- LLM 综合判断：是否 @ 机器人、话题上下文、风险等级、冷却状态
- 7 种回复意图：`SILENCE` / `ANSWER` / `AGREE` / `ASK_BACK` / `JOKE_LIGHT` / `COOL_DOWN` / `DEFLECT`
- 6 种回复风格：`short_reply` / `short_explain` / `ask_one_question` / `light_joke` / `cool_down` / `end_topic`

### 硬规则安全阀

`post_check_decision` 在 LLM 决策后执行：

- 置信度 < 0.6 → 强制静默
- 冲突话题强制 `COOL_DOWN`
- 间接消息（未 @ 未提）需要更高置信度（0.8）
- 20 秒冷却期，每话题间接消息最多插一次嘴
- 低价值消息（"嗯"、"？"等）不回复

### 风险检测

关键词匹配检测三类风险：

- `conflict`：急了、破防、sb、滚……
- `sensitive`：地域黑、政治、开盒、举报……
- `normal`：普通聊天

### 干运行模式

```bash
HIDE=1 uv run python main.py
```

只接收消息、做话题归类、做决策判断，**不发送任何 QQ 消息**。适合调试和话题数据收集。

### 配置热重载

运行时修改 `.env` 文件会自动重载以下配置（无需重启）：
- `BOT_ID`、`BOT_NAME`
- `HIDE` 开关
- LLM 参数

注意：`NAPCAT_WS_HOST` / `NAPCAT_WS_PORT` 修改后需要手动重启。

## 数据存储

```
data/topics.sqlite3
├── topics       # 话题：id, group_id, topic_no, title, summary, history, status, ...
└── messages     # 消息：group_id, message_id, user_id, nickname, text, topic_id, ...
```

- `topics.history`：最近 50 条消息的拼接（原始文本，用于话题延续判断）
- `topics.summary`：LLM 生成的语义摘要（用于话题列表展示和决策上下文）
