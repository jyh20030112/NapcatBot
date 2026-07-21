# NapcatBot

基于 NapCatQQ / OneBot v11 的 QQ 群聊 Agent。LLM 调用与 function calling 由
[SimAgentPlg](https://github.com/jiangyiheng15/SimAgentPlg) 提供，本项目负责
NapCat 适配、群聊状态管理、话题追踪、消息分析和 QQ 动作工具。

## 架构

4 条 Agent 管线，分工明确：

```
QQ 群消息 → NapCatQQ → WebSocket → NapcatWebSocketAdapter
                                        │
                                   GroupMessageHandler
                                   ┌──────┼──────┐
                                   │      │      │
                          TopicAgentService  │  NapcatReplyAgent
                          (话题归类+摘要)     │  (回复动作+MCP搜索)
                                         │
                                    DecisionService
                                    (消息分析·不决策)
```

| Agent               | 职责                                                 | 模型                    | 工具                                                                                         |
| ------------------- | ---------------------------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------- |
| **TopicClassifier** | 将消息归类到话题；后台异步生成话题摘要、群聊画像     | BaseAgent + tools       | `list_recent_topics`, `get_recent_group_messages`, `create_topic`, `assign_message_to_topic` |
| **TopicSummarizer** | 后台异步：将话题聊天记录总结为可读摘要               | BaseAgent + tools       | `update_topic_summary`                                                                       |
| **MessageAnalyzer** | 分析消息的情感导向、用户意图和风险（不判断该不该回） | BaseAgent，无工具       | 直接输出 JSON（reply_intent + risk_level + analysis）                                        |
| **ReplyAgent**      | 根据分析结果 + 上下文，自主判断是否回复、怎么回复    | BaseAgent + MCP + tools | `skip_reply`, `send_msg`, `send_at_msg`, `playwright__*`                                     |

ReplyAgent 可选的 MCP 工具（Playwright 浏览器）让机器人能主动搜索网页查证事实后再回复。

## 项目结构

```
NapcatBot/
├── main.py                          # 入口，WebSocket 监听 + .env 热重载
├── mcp_config.json                  # MCP 服务器配置（Playwright headless）
├── app/
│   ├── config.py                    # 环境变量读取（Settings）
│   ├── adapters/
│   │   └── napcat_ws.py             # WebSocket Server，接收 OneBot 事件
│   ├── core/
│   │   ├── message.py               # BotMessage 结构 + NapCat 原始事件解析
│   │   ├── group_state.py           # GroupState / TopicState 运行时状态
│   │   ├── reply.py                 # ReplyDecision 类型 + ReplyIntent + detect_risk + clean_reply
│   │   ├── context_builder.py       # 为四个 Agent 构建 prompt/task
│   │   ├── topic_store.py           # SQLite 持久化（topics + group_profiles）
│   │   └── json_logging.py          # 结构化 JSON 日志
│   ├── handlers/
│   │   └── group_message_handler.py # 消息处理主流程（编排 4 个 Agent）
│   ├── llms_tools/
│   │   ├── napcat_action_tools.py   # QQ 动作工具（skip_reply / send_msg / send_at_msg）
│   │   └── napcat_topic_tools.py    # 话题管理工具
│   └── services/
│       ├── topic_agent_service.py   # TopicClassifier + TopicSummarizer + 群聊画像
│       ├── decision_agent_service.py# MessageAnalyzer（消息分析）
│       └── reply_agent_service.py   # ReplyAgent（回复执行 + MCP 搜索）
└── data/
    └── topics.sqlite3               # 话题和群聊画像持久化（自动创建）
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
BOT_ID=XXXX
BOT_NAME=XXXX

# 主人的名字与 QQ 号（机器人会重视主人的话，但绝不对外泄露）
OWNER_NAME=XXXX
OWNER_ID=XXXX

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

- LLM 驱动的消息话题归类（TopicClassifier）
- 支持通过 `reply` 继承原消息的话题（内存快速路径 + DB 写入）
- 话题摘要自动生成：首次归类后，后台异步调用 LLM 将聊天记录总结为可读摘要
- 话题自动清理：10 分钟无新消息 → 标记为 `inactive`；群聊画像更新后删除
- SQLite 持久化，重启不丢失

### 群聊画像

- 每 24 小时自动生成：汇总群内所有话题（活跃 + 沉寂），LLM 生成群聊画像
- 画像内容：群聊领域、互动风格、成员特征（200 字以内）
- 画像会注入 TopicClassifier、MessageAnalyzer、ReplyAgent 的上下文
- 画像生成后自动清理已沉寂话题

### 消息分析

MessageAnalyzer 分析每条消息，输出三项结构化信息：

- **reply_intent**：ASKING / CHATTING / AGREEING / ARGUING / GREETING / DEFUSING / OTHER
- **risk_level**：normal / sensitive / conflict
- **analysis**：3-6 句中文分析，描述发送者意图和话题氛围

注意：MessageAnalyzer 只分析，不决策。是否回复由 ReplyAgent 自行判断。

### 风险检测

两层风险识别：

1. **关键词匹配**（`detect_risk`）：检测冲突词（急了、破防、sb...）和敏感词（地域黑、开盒、政治...）
2. **LLM 分析**：MessageAnalyzer 结合上下文判断风险等级

### 回复执行

ReplyAgent 拥有三种工具：

- `skip_reply` — 不回复（正常选择，鼓励沉默而非尬聊）
- `send_msg` — 向群内发普通消息
- `send_at_msg` — @ 某人并发送消息

可选 MCP 工具（`playwright__*`）：当群友讨论需要查证的事实时，ReplyAgent 可以主动搜索网页获取准确信息后再回复。

### 身份保护

所有 Agent 的系统提示词包含身份保护规则：

- 绝不承认自己是机器人、AI、大模型、程序
- 用真人方式回应质疑（"我要是机器人早宕机了"）
- 绝不泄露主人的 QQ 号、名字等任何信息

### 干运行模式

```bash
HIDE=1 uv run python main.py
```

只接收消息、做话题归类、分析消息，**不发送任何 QQ 消息**。适合调试和数据收集。

### 配置热重载

运行时修改 `.env` 文件会自动重载以下配置（无需重启）：

- `BOT_ID`、`BOT_NAME`
- `OWNER_NAME`、`OWNER_ID`
- `HIDE` 开关
- LLM 参数

注意：`NAPCAT_WS_HOST` / `NAPCAT_WS_PORT` 修改后需要手动重启。

## 数据存储

```
data/topics.sqlite3
├── topics           # 话题：id, group_id, topic_no, title, summary, history, status, ...
└── group_profiles   # 群聊画像：group_id, profile, updated_at
```

- `topics.history`：最近 50 条消息的拼接（原始文本，用于话题延续判断）
- `topics.summary`：LLM 生成的语义摘要（用于话题列表展示和决策上下文）
- `topics.status`：active（活跃）/ inactive（超 10 分钟无新消息，等画像更新后清理）
- `group_profiles.profile`：LLM 生成的群聊画像文本（每 24 小时更新）

## 消息处理流程

```
1. 收到群消息
2. normalize_group_message  →  解析/过滤/标准化
3. state.add_message        →  存入最近 80 条消息
4. TopicClassifier          →  归类话题（reply_to 快速路径 或 LLM 归类）
5. _load_profile            →  读取群聊画像
6. MessageAnalyzer          →  分析意图/风险（失败 → 静默跳过本条）
7. build_action_task        →  拼接分析结果 + 话题 + 24条上下文
8. ReplyAgent               →  自主判断是否回复、如何回复（失败 → 静默跳过）
9. record_bot_reply         →  将机器人回复插入消息流
```

## 边界保护

- LLM 崩溃：三级 try/except，失败静默跳过不丢消息
- DB 冲突：topic_no 使用 MAX 而非 COUNT，删除旧话题不会碰撞
- 竞态条件：`send_action_and_wait` 先注册 Future 再发送，避免响应丢失
- 消息超限：内存中最多保留 80 条消息，话题最多 20 条
- DB 膨胀：10 分钟无新消息的话题标记为 inactive，画像更新后自动删除
- MCP 失败：静默降级，搜索工具不可用时不影响正常回复
