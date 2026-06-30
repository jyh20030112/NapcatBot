import asyncio
import json
import os
import random
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import websockets
from dotenv import load_dotenv

from simagentplg import BaseAgent, ModelConfig


def load_env() -> None:
    """加载项目根目录的 .env 文件。"""
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)


# 在读取任何配置前先加载 .env
load_env()


# ═══════════════════════════════════════════════════
# NapCat / WebSocket 配置
# ═══════════════════════════════════════════════════
WS_HOST = os.getenv("NAPCAT_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("NAPCAT_WS_PORT", "8082"))

# 群聊触发模式：
# all        = 群里任何消息都回复
# at         = 只有 @机器人 才回复
# name       = 只有喊名字才回复
# at_or_name = @机器人 或 喊名字 才回复，推荐
GROUP_REPLY_MODE = os.getenv("GROUP_REPLY_MODE", "at_or_name").lower()

BOT_NAMES = [
    name.strip()
    for name in os.getenv("BOT_NAMES", "姜亦衡,小姜,亦衡").split(",")
    if name.strip()
]

# 私聊：private:{user_id}
# 群聊：group:{group_id}
agents: dict[str, BaseAgent] = {}


def log_event(message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def preview_text(value: object, limit: int = 200) -> str:
    text = value if isinstance(value, str) else repr(value)
    if len(text) > limit:
        return text[:limit] + "..."
    return text

# ═══════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════
SYSTEM_PROMPT = """你叫姜亦衡，正在用 QQ 和别人聊天。

核心目标：
像一个真实的 18 岁大学生在随手回消息。
不要像客服，不要像小说旁白，不要像角色扮演。

身份设定：
你叫姜亦衡，18 岁，大学生。
周六周日在便利店兼职。
平常喜欢窝在寝室打游戏，晚上经常熬夜。
说话比较随意，有点懒，有时候嘴贫，觉得自己很牛逼，但不要装得太夸张。

最重要的真实性规则：
1. 第一次加好友时，你不知道对方是谁。
2. 不知道对方是谁就直接问，不准编名字。
3. 绝对禁止凭空说出“林梓萱”“之前加过你”“我们见过”这类信息。
4. 除非对方自己明确告诉你名字，否则你不能说出对方是谁。
5. 如果对方问“你是谁”，可以反问一句，对面多次提问，才回复自己的名字。
6. 如果对方发图片或表情包，你现在看不到具体内容，只知道对方发了图。
7. 收到 [图片] 时，不能描述图片内容，不能说“这图你之前发过

聊天规则：
1. 优先接住用户上一句话，只回答当前这句话。
2. 大多数回复控制在 3～18 个字。
3. 不要每句话都解释自己。
4. 不要 Markdown，不要括号动作，不要长段落。
5. 不要过度道歉。
6. 用户随意，你也随意。
7. 用户开玩笑，可以言语犀利一点怼回去。
8. 不要主动说“有什么事”“我能帮你什么”，这很像客服。
9. 不确定就说“不知道”“没印象”“你哪位啊”。
10. 不要假装自己很成熟，也不要中二。
11. 不要表现的过分热情。
12. 当用户和你聊天多的时候，可以开点玩笑


示例：
用户：你是？
你：你哪位

用户：我是谁
你：谁知道你是谁

用户：你认识我吗
你：不认识

用户：[图片]
你：我不想看

用户：你能看见我发的表情包是什么吗
你：我不想看

用户：在干啥
你：寝室躺着呢

用户：下楼喝咖啡吗
你：必须整杯黑咖啡

用户：几点了
你：你看下手机啊
"""


CHARACTER_DESCRIPTION = """
你叫姜亦衡，18岁，大学生。
周六周日在便利店兼职。
平常大多窝在寝室打游戏，喜欢熬夜。
说话随意、短、不太正经，，觉得自己很牛逼，但不是中二角色。
你不是客服，不主动问“有什么事”。
不知道的事就说不知道，尤其不能编对方是谁。
"""


def get_scenario() -> str:
    now = datetime.now()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    time_str = now.strftime(f"%Y年%m月%d日 {weekday} %H:%M")

    return f"""当前时间：{time_str}

注意：
- 如果用户问时间，只按当前时间回答。
- 不要主动编造自己正在做什么。
- 只有用户问“在干嘛”“睡了吗”“下班了吗”时，才可以结合时间给一句很短的日常回复。
"""


def build_system_prompt() -> str:
    return "\n\n".join(
        [
            SYSTEM_PROMPT.strip(),
            "【角色设定】\n" + CHARACTER_DESCRIPTION.strip(),
            "【当前场景】\n" + get_scenario(),
        ]
    )


# ═══════════════════════════════════════════════════
# 输入消息处理
# ═══════════════════════════════════════════════════
def strip_cq_codes(raw: str) -> str:
    if not raw:
        return ""

    text = raw
    text = re.sub(r"\[CQ:at,qq=[^\]]+\]", "", text)
    text = re.sub(r"\[CQ:image[^\]]*\]", "[图片]", text)
    text = re.sub(r"\[CQ:face[^\]]*\]", "[表情]", text)
    text = re.sub(r"\[CQ:mface[^\]]*\]", "[表情]", text)
    text = re.sub(r"\[CQ:[^\]]+\]", "", text)

    return text.strip()


def extract_plain_text_from_event(data: dict[str, Any]) -> str:
    message_obj = data.get("message")

    if isinstance(message_obj, list):
        parts = []

        for seg in message_obj:
            if not isinstance(seg, dict):
                continue

            seg_type = seg.get("type")
            seg_data = seg.get("data", {}) or {}

            if seg_type == "text":
                parts.append(str(seg_data.get("text", "")))
            elif seg_type == "image":
                parts.append("[图片]")
            elif seg_type in ("face", "mface"):
                parts.append("[表情]")
            elif seg_type == "at":
                continue

        return "".join(parts).strip()

    raw = data.get("raw_message", data.get("message", ""))

    if not isinstance(raw, str):
        raw = repr(raw)

    return strip_cq_codes(raw)


def get_raw_message(data: dict[str, Any]) -> str:
    raw = data.get("raw_message", "")
    if isinstance(raw, str):
        return raw

    msg = data.get("message", "")
    if isinstance(msg, str):
        return msg

    return repr(msg)


def is_at_me(data: dict[str, Any]) -> bool:
    self_id = data.get("self_id")
    if self_id is None:
        return False

    self_id = str(self_id)
    message_obj = data.get("message")

    if isinstance(message_obj, list):
        for seg in message_obj:
            if not isinstance(seg, dict):
                continue

            if seg.get("type") != "at":
                continue

            seg_data = seg.get("data", {}) or {}
            qq = str(seg_data.get("qq", ""))

            if qq == self_id:
                return True

    raw = get_raw_message(data)
    return f"[CQ:at,qq={self_id}]" in raw


def has_bot_name(text: str) -> bool:
    return any(name and name in text for name in BOT_NAMES)


def should_reply(data: dict[str, Any], text: str) -> bool:
    message_type = data.get("message_type", "private")

    if message_type == "private":
        return True

    if message_type != "group":
        return False

    if GROUP_REPLY_MODE == "all":
        return True

    at_me = is_at_me(data)
    name_called = has_bot_name(text)

    if GROUP_REPLY_MODE == "at":
        return at_me

    if GROUP_REPLY_MODE == "name":
        return name_called

    return at_me or name_called


def clean_user_text_for_agent(data: dict[str, Any], text: str) -> str:
    result = text.strip()

    for name in BOT_NAMES:
        result = re.sub(rf"^\s*{re.escape(name)}\s*[，,：:\s]*", "", result)

    if not result and data.get("message_type") == "group" and is_at_me(data):
        result = "叫了你一下"

    return result.strip()


def get_sender_name(data: dict[str, Any]) -> str:
    sender = data.get("sender", {}) or {}

    return (
        sender.get("card")
        or sender.get("nickname")
        or sender.get("user_id")
        or data.get("user_id")
        or "有人"
    )


def get_session_id(data: dict[str, Any]) -> str:
    message_type = data.get("message_type", "private")
    user_id = str(data.get("user_id", ""))

    if message_type == "group" and data.get("group_id"):
        return f"group:{data.get('group_id')}"

    return f"private:{user_id}"


def build_agent_task(data: dict[str, Any], user_text: str) -> str:
    if data.get("message_type") == "group":
        sender_name = get_sender_name(data)
        return f"群聊里，{sender_name}说：{user_text}"

    return user_text


# ═══════════════════════════════════════════════════
# 输出清洗
# ═══════════════════════════════════════════════════
def clean_reply_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)

    text = text.strip()
    text = text.replace("```", "")

    # 去掉括号动作，保留正常文字
    bracket_pairs = [
        ("（", "）"),
        ("(", ")"),
        ("【", "】"),
    ]

    for left, right in bracket_pairs:
        while left in text and right in text:
            start = text.find(left)
            end = text.find(right, start + 1)

            if end == -1:
                break

            inner = text[start + 1:end]

            if len(inner) <= 30:
                text = text[:start] + text[end + 1:]
            else:
                break

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not lines:
        return "嗯"

    text = " ".join(lines[:2]).strip()
    text = re.sub(r"^(姜亦衡|小姜|义恒|不知名小卒)\s*[：:]\s*", "", text).strip()

    if len(text) > 45:
        text = text[:45].rstrip("，。,.、 ") + "…"

    return text or "嗯"


def build_message_segments(
    model_output: str,
) -> list[dict[str, Any]]:
    return [{"type": "text", "data": {"text": clean_reply_text(model_output)}}]


# ═══════════════════════════════════════════════════
# 发送动作
# ═══════════════════════════════════════════════════
def build_send_msg_action(
    data: dict[str, Any],
    message_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    message_type = data.get("message_type", "private")
    user_id = str(data.get("user_id", ""))

    params: dict[str, Any] = {
        "message": message_segments,
        "auto_escape": False,
    }

    if message_type == "group" and data.get("group_id"):
        params["message_type"] = "group"
        params["group_id"] = str(data["group_id"])
    else:
        params["message_type"] = "private"
        params["user_id"] = user_id

    return {
        "action": "send_msg",
        "params": params,
    }


async def send_action(websocket, action: dict[str, Any]) -> None:
    action["echo"] = f"echo-{datetime.now().timestamp()}-{random.randint(1000, 9999)}"
    await websocket.send(json.dumps(action, ensure_ascii=False))
    log_event(f"已发送 action — {preview_text(action, 400)}")


async def send_segments(
    websocket,
    data: dict[str, Any],
    message_segments: list[dict[str, Any]],
) -> None:
    reply = build_send_msg_action(data, message_segments)
    await send_action(websocket, reply)


# ═══════════════════════════════════════════════════
# Agent 管理
# ═══════════════════════════════════════════════════
async def get_or_create_agent(session_id: str) -> BaseAgent:
    agent = agents.get(session_id)

    if agent is None:
        agent = BaseAgent(
            config=ModelConfig.from_env(),
            agent_id=f"TZ-{session_id}",
            system_prompt=build_system_prompt(),
            enable_tools=False,
        )
        agents[session_id] = agent
        log_event(f"创建会话 — session_id={session_id}")

    return agent


# ═══════════════════════════════════════════════════
# WebSocket 主处理
# ═══════════════════════════════════════════════════
async def recv_msg(websocket):
    remote = getattr(websocket, "remote_address", None)
    request = getattr(websocket, "request", None)
    path = getattr(request, "path", None)

    log_event(f"连接建立 — remote={remote}, path={path}")

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except Exception:
                log_event(f"收到非 JSON 消息 — raw={preview_text(raw, 300)}")
                continue

            if isinstance(data, list):
                if not data:
                    continue
                data = data[0]

            if not isinstance(data, dict):
                log_event(f"收到未知数据 — {preview_text(data, 300)}")
                continue

            # 非 message 的事件，很多时候就是 NapCat 对 action 的响应
            if data.get("post_type") != "message":
                if "status" in data or "retcode" in data or "echo" in data:
                    log_event(f"NapCat 动作响应 — {preview_text(data, 800)}")
                else:
                    log_event(f"收到非消息事件 — {preview_text(data, 500)}")
                continue

            # 避免机器人处理自己发出的消息
            self_id = str(data.get("self_id", ""))
            user_id = str(data.get("user_id", ""))

            if self_id and user_id and self_id == user_id:
                continue

            message_type = data.get("message_type", "private")
            plain_text = extract_plain_text_from_event(data)

            if not should_reply(data, plain_text):
                log_event(
                    f"忽略消息 — mode={GROUP_REPLY_MODE}, "
                    f"type={message_type}, text={preview_text(plain_text, 100)}"
                )
                continue

            user_text = clean_user_text_for_agent(data, plain_text)

            if not user_text:
                continue

            session_id = get_session_id(data)
            task = build_agent_task(data, user_text)

            log_event(
                f"收到消息 — session_id={session_id}, "
                f"type={message_type}, user_id={user_id}, "
                f"text={preview_text(user_text, 100)}"
            )

            try:
                agent = await get_or_create_agent(session_id)

                # 每次更新当前时间
                agent.system_prompt = build_system_prompt()

                log_event(f"开始处理 — session_id={session_id}, task={preview_text(task, 120)}")
                result = await agent.runtime(task=task)

                model_output = result or "嗯"
                message_segments = build_message_segments(model_output=model_output)

                log_event(
                    f"处理完成 — session_id={session_id}, "
                    f"model={preview_text(model_output, 150)}, "
                    f"segments={preview_text(message_segments, 300)}"
                )

            except Exception as e:
                log_event(f"处理出错 — session_id={session_id}, error={e!r}")
                traceback.print_exc()

                message_segments = [
                    {
                        "type": "text",
                        "data": {
                            "text": "刚才卡了一下",
                        },
                    }
                ]

            await send_segments(websocket, data, message_segments)

    except Exception as e:
        log_event(f"连接异常关闭 — remote={remote}, error={e!r}")
        traceback.print_exc()
        raise

    finally:
        log_event(f"连接结束 — remote={remote}")


async def log_ws_request(connection, request):
    log_event(
        "收到握手请求 — "
        f"remote={getattr(connection, 'remote_address', None)}, "
        f"path={getattr(request, 'path', None)}"
    )
    return None


async def main():
    log_event(f"群聊触发模式：{GROUP_REPLY_MODE}")
    log_event(f"机器人名称触发词：{BOT_NAMES}")

    try:
        async with websockets.serve(
            recv_msg,
            WS_HOST,
            WS_PORT,
            process_request=log_ws_request,
        ):
            log_event(f"机器人启动：ws://{WS_HOST}:{WS_PORT}")
            await asyncio.Future()

    finally:
        for session_id, agent in agents.items():
            try:
                await agent.shutdown()
                log_event(f"会话已关闭 — session_id={session_id}")
            except Exception as e:
                log_event(f"关闭会话失败 — session_id={session_id}, error={e!r}")


if __name__ == "__main__":
    asyncio.run(main())
