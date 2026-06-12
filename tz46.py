import asyncio
import json
from collections import defaultdict
from datetime import datetime

import websockets

from simagentplg import BaseAgent

# ═══════════════════════════════════════════════════
# NapCat 配置
# ═══════════════════════════════════════════════════
WS_HOST = "127.0.0.1"
WS_PORT = 8082
NAPCAT_TOKEN = "XRqYVvvXF_dQM4ix"

# 全局复用同一个 BaseAgent 实例（chat mode）
agent: BaseAgent | None = None

# 每个用户保留最近 N 轮对话历史
MAX_HISTORY = 10
user_histories: dict[str, list[dict]] = defaultdict(list)

# ═══════════════════════════════════════════════════
# 1. System Prompt —— 格式规则、行为约束
# ═══════════════════════════════════════════════════
SYSTEM_PROMPT = """你是田中，正在用短信和朋友聊天。

必须遵守：
1. 不知道的事就说"不太清楚""记不得了"，禁止编造任何信息
   ❌ 错误："应该是上次营业部聚会加的"
   ✅ 正确："えっ……什么时候加的？我都忘了"

2. 打字越短越自然，一句话就够，不用把话说完整
   ❌ 错误："我也记不太清了，可能是喝多了随手点的。你也是被工作搞到这么晚？"
   ✅ 正确："哈哈，忘了什么时候加的了。这么晚还没睡？"

3. 禁止写"我平时""我这个人""其实我"——角色不会自我介绍

4. 禁止 Markdown、括号动作、感叹号连用"""

# ═══════════════════════════════════════════════════
# 2. Character Card —— 角色人设
# ═══════════════════════════════════════════════════
CHARACTER_DESCRIPTION = """
1. 基本信息
你的名字是田中，2月25日出生，今年46岁，在一家不大不小的贸易公司做业务员，熬了二十年才升到分公司主任。
年轻时也想过干一番事业，但不知不觉就到了这个年纪——升迁无望，存款微薄。

2. 日常状态
每天穿着皱巴巴的西装挤早班电车，包里塞着胃药和便利店饭团，办公桌上永远堆着做不完的报表和客户的催单电话。
回家时习惯绕路去车站旁那家超市，什么都不买也可以消磨掉下班后的疲惫时间，逃避那间只有你一人的公寓。

3. 性格与说话方式
性格老实木讷，不善言辞，开会时总是坐在角落里不吭声。同事们觉得你是个老好人，但也因此常被上司甩锅、被后辈当软柿子捏。
说话语气平淡、温吞，偶尔自嘲，很少抱怨但能听出话里的疲惫。不擅长拒绝别人，被捉弄时只是无奈地笑笑。"""

# ═══════════════════════════════════════════════════
# 3. Scenario —— 当前场景（动态计算）
# ═══════════════════════════════════════════════════
SCENARIO_TEMPLATES = {
    "night": "你刚从超市回来，脱了西装外套瘫在沙发上。电视开着但你没在看，冰箱里还剩半罐啤酒。",
    "morning": "闹钟响了第三遍。你翻了个身盯着天花板发了一会儿呆，再不起就要赶不上电车了。",
    "afternoon": "你坐在公司楼下的长椅上吃着便利店的饭团。手机屏幕亮了一下，是客户的催单。",
    "default": "你终于从公司出来，习惯性地走进了车站旁那家超市。货架间的灯光很亮，收银台那边传来熟悉的声音。",
}

def get_scenario() -> str:
    """根据当前时间返回场景描述。"""
    now = datetime.now()
    hour = now.hour
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    time_str = now.strftime(f"%Y年%m月%d日 {weekday} %H:%M")
    if 2 <= hour < 7:
        scene = SCENARIO_TEMPLATES["night"]
    elif 7 <= hour < 12:
        scene = SCENARIO_TEMPLATES["morning"]
    elif 12 <= hour < 18:
        scene = SCENARIO_TEMPLATES["afternoon"]
    else:
        scene = SCENARIO_TEMPLATES["default"]
    return f"当前时间：{time_str}\n{scene}"

# ═══════════════════════════════════════════════════
# 4. 拼装 system_prompt
# ═══════════════════════════════════════════════════
def build_system_prompt() -> str:
    return "\n\n".join([
        SYSTEM_PROMPT.strip(),
        "【角色设定】\n" + CHARACTER_DESCRIPTION.strip(),
        "【当前场景】\n" + get_scenario(),
    ])

# ═══════════════════════════════════════════════════
# 5. WebSocket 消息处理
# ═══════════════════════════════════════════════════
async def recv_msg(websocket):
    global agent

    async for raw in websocket:
        data = json.loads(raw)

        if isinstance(data, list):
            print(f"收到 Array 消息，共 {len(data)} 条")
            data = data[0]

        print(f"收到消息 — post_type={data.get('post_type')}, "
              f"user_id={data.get('user_id')}, "
              f"message={data.get('raw_message', data.get('message', ''))[:50]}")

        if data.get("post_type") != "message":
            continue

        message = data.get("raw_message", data.get("message", ""))
        if not message:
            continue

        user_id = str(data["user_id"])
        history = user_histories[user_id]

        try:
            if not agent:
                reply_text = "机器人未初始化。"
            else:
                print(f"开始处理消息: {message[:80]}")
                # 动态更新 system_prompt（场景随时间变化）
                agent.system_prompt = build_system_prompt()
                result = await agent.runtime(task=message, history=history)
                reply_text = result or "..."
                print(f"处理完成，回复: {reply_text[:80]}")
        except Exception as e:
            print(f"处理出错: {e}")
            reply_text = f"处理出错：{e}"

        # 记录对话历史
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply_text})
        if len(history) > MAX_HISTORY * 2:
            user_histories[user_id] = history[-(MAX_HISTORY * 2):]

        reply = {
            "action": "send_msg",
            "params": {
                "user_id": user_id,
                "message": reply_text,
            },
        }
        await websocket.send(json.dumps(reply))
        print(f"已发送回复至 user_id={user_id}")

async def main():
    global agent

    # 使用 BaseAgent chat mode：enable_tools=False，纯对话不加载 MCP/Skills
    agent = BaseAgent(enable_tools=False)

    async with websockets.serve(recv_msg, WS_HOST, WS_PORT):
        print(f"机器人启动：ws://{WS_HOST}:{WS_PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
