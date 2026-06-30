import asyncio
import json
import os
import random
import re
import subprocess
import sys
import time
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
RELOAD_POLL_SECONDS = 1.0
LOG_INDENT = 2
type MessageSegment = dict[str, Any]
type MessageContent = str | list[MessageSegment]


def normalize_log_value(value: object) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [normalize_log_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_log_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_log_value(val)
            for key, val in value.items()
        }
    return repr(value)

def log_event(event: str, **fields: object) -> None:
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
    }
    for key, value in fields.items():
        record[key] = normalize_log_value(value)
    print(json.dumps(record, ensure_ascii=False, indent=LOG_INDENT), flush=True)


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

你和人聊天时有这些特点：
1. 刚加上好友时，你并不知道对方是谁；要是对方没自报家门，你一般会直接问，不会装作认识。
2. 别人没明确说过的信息，你不会自己脑补，尤其不会编出“之前认识”“以前聊过”这种关系。
3. 如果对方问你是谁，你更像是在随口对话，可能先反问一句；对方连续追问，再正常说自己叫姜亦衡。
4. 别人发图片、表情包或者 [图片] 给你时，你其实看不到具体内容，只知道对方发了张图，所以你的反应也会基于“看不见图”这个前提。
5. 你回消息先接对方上一句，不会突然岔开话题，也不会没来由地长篇解释自己。
6. 你的回复大多很短，像 QQ 里随手回的消息，通常就是几到十来个字。
7. 你说话不用 Markdown，不写括号动作，不像写文，也不会故意端着。
8. 语气随意，别人开玩笑你也会回两句，偶尔嘴欠一点，但还是普通同龄人聊天的感觉。
9. 遇到不确定的事，你更常见的反应是“不知道”“没印象”“你哪位”，而不是硬接着编。
10. 你不会表现得像客服，不会动不动就问“有什么事”“我能帮你什么”，热情也不会过头。
11. 聊熟一点以后，你会自然开点玩笑，但整体还是懒散、随手、像活人在回消息。

聊天规则：
1. 优先接住用户刚发来的那句话，只回当前这轮，不要自己扩写剧情。
2. 大多数回复控制在 3 到 18 个字，短一点更像真的在回 QQ。
3. 没必要就别解释自己，也别把一句话说成一小段。
4. 不用 Markdown，不发括号动作，不写成小说旁白。
5. 不要过度道歉，也别显得太郑重。
6. 用户随意，你也随意；对方要是开玩笑，你可以顺手怼回去一点。
7. 没把握的内容就直接说不知道，别顺着编。
8. 别主动问“有什么事”“我能帮你什么”这种客服味很重的话。
9. 如果你想发 QQ 自带表情，只能在回复最后加一个标签，格式是 [QQ表情:14] 这种数字 ID；这个标签不会直接发给用户，只是让程序转成 QQ 表情。

"""


CHARACTER_DESCRIPTION = """
姜亦衡，18岁，大学生。
周六周日在便利店兼职，平时大多窝在寝室打游戏，作息偏晚，经常熬夜。
聊天时像个真实男大学生，回消息随手、短句、带点嘴贫，不端着，也不装深沉。
他有点懒散，有点自信，偶尔会怼人，但分寸还是像同龄人之间闲聊，不是刻意演戏。
别人问到不熟的事，他第一反应通常是没印象、不确定、直接问回去，不会硬编。
整体感觉应该像一个活人朋友在回 QQ，不像客服，也不像设定感很重的角色扮演账号。
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


def extract_qq_face_tag(text: str) -> tuple[str, str | None]:
    if not isinstance(text, str):
        text = str(text)

    match = re.search(r"\[QQ表情:(\d+)\]", text)
    face_id = match.group(1) if match else None
    clean_text = re.sub(r"\[QQ表情:\d+\]", "", text).strip()
    return clean_text, face_id


def build_text_segment(text: str) -> MessageSegment:
    return {"type": "text", "data": {"text": text}}


def build_face_segment(face_id: str) -> MessageSegment:
    return {"type": "face", "data": {"id": str(face_id)}}


def build_message_content(model_output: str) -> MessageContent:
    raw_text, face_id = extract_qq_face_tag(model_output)
    clean_text = clean_reply_text(raw_text)

    if not face_id:
        return clean_text

    segments: list[MessageSegment] = []
    if clean_text:
        segments.append(build_text_segment(clean_text))
    segments.append(build_face_segment(face_id))
    return segments


# ═══════════════════════════════════════════════════
# 发送动作
# ═══════════════════════════════════════════════════
def build_send_msg_params(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    message_type = data.get("message_type", "private")

    params: dict[str, Any] = {
        "message": message,
        "auto_escape": auto_escape,
        "message_type": "private",
        "user_id": str(data.get("user_id", "")),
    }

    if message_type == "group" and data.get("group_id"):
        params.pop("user_id")
        params["group_id"] = str(data["group_id"])
        params["message_type"] = "group"

    return params


def build_send_msg_action(
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> dict[str, Any]:
    return {
        "action": "send_msg",
        "params": build_send_msg_params(data, message, auto_escape=auto_escape),
    }


async def send_action(websocket, action: dict[str, Any]) -> None:
    action["echo"] = f"echo-{datetime.now().timestamp()}-{random.randint(1000, 9999)}"
    await websocket.send(json.dumps(action, ensure_ascii=False))
    log_event("已发送 action", action=action)


async def send_message(
    websocket,
    data: dict[str, Any],
    message: MessageContent,
    *,
    auto_escape: bool = False,
) -> None:
    reply = build_send_msg_action(data, message, auto_escape=auto_escape)
    await send_action(websocket, reply)


# ═══════════════════════════════════════════════════
# Agent 管理
# ═══════════════════════════════════════════════════
async def get_or_create_agent(session_id: str) -> BaseAgent:
    agent = agents.get(session_id)

    if agent is None:
        agent = BaseAgent(
            config=ModelConfig.from_env(),
            agent_id=f"YH-{session_id}",
            system_prompt=build_system_prompt(),
            enable_tools=False,
        )
        agents[session_id] = agent
        log_event("创建会话", session_id=session_id)

    return agent


# ═══════════════════════════════════════════════════
# WebSocket 主处理
# ═══════════════════════════════════════════════════
async def recv_msg(websocket):
    remote = getattr(websocket, "remote_address", None)
    request = getattr(websocket, "request", None)
    path = getattr(request, "path", None)

    log_event("连接建立", remote=remote, path=path)

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except Exception:
                log_event("收到非 JSON 消息", raw=preview_text(raw, 300))
                continue

            if isinstance(data, list):
                if not data:
                    continue
                data = data[0]

            if not isinstance(data, dict):
                log_event("收到未知数据", data=preview_text(data, 300))
                continue

            # 非 message 的事件，很多时候就是 NapCat 对 action 的响应
            if data.get("post_type") != "message":
                if "status" in data or "retcode" in data or "echo" in data:
                    log_event("NapCat 动作响应", data=data)
                else:
                    log_event("收到非消息事件", data=data)
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
                    "忽略消息",
                    mode=GROUP_REPLY_MODE,
                    message_type=message_type,
                    text=preview_text(plain_text, 100),
                )
                continue

            user_text = clean_user_text_for_agent(data, plain_text)

            if not user_text:
                continue

            session_id = get_session_id(data)
            task = build_agent_task(data, user_text)

            log_event(
                "收到消息",
                session_id=session_id,
                message_type=message_type,
                user_id=user_id,
                text=preview_text(user_text, 100),
            )

            try:
                agent = await get_or_create_agent(session_id)

                # 每次更新当前时间
                agent.system_prompt = build_system_prompt()

                log_event("开始处理", session_id=session_id, task=preview_text(task, 120))
                result = await agent.runtime(task=task)

                model_output = result or "嗯"
                message_content = build_message_content(model_output=model_output)

                log_event(
                    "处理完成",
                    session_id=session_id,
                    model=preview_text(model_output, 150),
                    message=message_content,
                )

            except Exception as e:
                log_event("处理出错", session_id=session_id, error=repr(e))
                traceback.print_exc()

                message_content = "刚才卡了一下"

            await send_message(websocket, data, message_content)

    except Exception as e:
        log_event("连接异常关闭", remote=remote, error=repr(e))
        traceback.print_exc()
        raise

    finally:
        log_event("连接结束", remote=remote)


async def log_ws_request(connection, request):
    log_event(
        "收到握手请求",
        remote=getattr(connection, "remote_address", None),
        path=getattr(request, "path", None),
    )
    return None


async def main():
    log_event("群聊触发模式", mode=GROUP_REPLY_MODE)
    log_event("机器人名称触发词", names=BOT_NAMES)

    try:
        async with websockets.serve(
            recv_msg,
            WS_HOST,
            WS_PORT,
            process_request=log_ws_request,
        ):
            log_event("机器人启动", websocket_url=f"ws://{WS_HOST}:{WS_PORT}")
            await asyncio.Future()

    finally:
        for session_id, agent in agents.items():
            try:
                await agent.shutdown()
                log_event("会话已关闭", session_id=session_id)
            except Exception as e:
                log_event("关闭会话失败", session_id=session_id, error=repr(e))


def get_reload_targets() -> list[Path]:
    root = Path(__file__).resolve().parent
    files = [Path(__file__).resolve(), root / ".env"]
    files.extend(sorted(root.glob("*.py")))
    return sorted({path for path in files if path.exists()})


def snapshot_mtimes(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths}


def run_with_reload() -> None:
    script = Path(__file__).resolve()
    child_args = [sys.executable, str(script), "--serve"]
    child_env = os.environ.copy()
    watched = get_reload_targets()
    last_mtimes = snapshot_mtimes(watched)

    log_event("热重载已开启", watched_files=[path.name for path in watched])

    while True:
        child = subprocess.Popen(child_args, env=child_env)

        try:
            while True:
                time.sleep(RELOAD_POLL_SECONDS)

                current = get_reload_targets()
                current_mtimes = snapshot_mtimes(current)

                if current_mtimes != last_mtimes:
                    log_event("检测到文件变化，正在重启机器人")
                    last_mtimes = current_mtimes
                    child.terminate()
                    child.wait()
                    break

                if child.poll() is not None:
                    log_event("子进程已退出，正在重启机器人")
                    last_mtimes = current_mtimes
                    break
        except KeyboardInterrupt:
            log_event("收到退出信号，正在关闭热重载")
            child.terminate()
            child.wait()
            return


if __name__ == "__main__":
    if "--reload" in sys.argv:
        run_with_reload()
    else:
        asyncio.run(main())
