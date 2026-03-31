from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from .state import MessagesState
from src.tools.sql_tools import execute_sql

llm = None
llm_with_tools = None

def initialize_llm(llm_instance):
    global llm, llm_with_tools
    llm = llm_instance
    llm_with_tools = llm.bind_tools([execute_sql])

async def intent_node(state: MessagesState):
    """【门卫】四路智能分流器"""
    global llm
    if not state.get("messages") or llm is None:
        return {"route": "chat"}

    last_msg = state["messages"][-1].content.strip()
    system_prompt = """你是一个金融侦探前台。请分类：
    1. 【CHAT】：打招呼、闲聊。回复格式：【CHAT】+ 幽默回复。
    2. 【META】：查表名、表结构。回复格式：只回【META】。
    3. 【BUSINESS】：查具体数字、逾期金额。回复格式：只回【BUSINESS】。
    4. 【ANALYSIS】：问“为什么”、查原因、做归因分析。回复格式：只回【ANALYSIS】。"""

    res = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg)])
    res_text = res.content.upper()

    if "CHAT" in res_text:
        reply = res.content.replace("【CHAT】", "").strip()
        return {"messages": [AIMessage(content=reply or "您好！")], "route": "chat"}
    elif "META" in res_text:
        return {"route": "meta"}
    elif "ANALYSIS" in res_text:
        return {"route": "analysis"}
    else:
        return {"route": "business"}

async def check_data_freshness_node(state: MessagesState):
    """【哨兵】查水位"""
    date = "2024-12-23"
    return {"messages": [SystemMessage(content=f"当前数据截止到 {date}。")], "data_freshness": date}


async def generate_sql_node(state: MessagesState):
    """
    大脑节点：支持纠错且永不卡死的稳固版
    """
    global llm_with_tools
    if llm_with_tools is None:
        return {"messages": [AIMessage(content="❌ 办案大脑连接中断。")]}

    # 1. 提取最近的消息，判断是否含有错误
    messages = state["messages"]
    last_msg_content = messages[-1].content if messages else ""

    # 2. 动态构造纠错指令 (方案三)
    correction_prompt = ""
    if "ERROR" in last_msg_content:
        correction_prompt = (
            "\n[重点纠错] 上一次查询失败，错误信息为: {last_msg_content}\n"
            "请分析错误（如表名单复数写错），修正后重新调用 `execute_sql`。"
        ).format(last_msg_content=last_msg_content)

    # 3. 方案二：核心约束指令
    sys_instruction = SystemMessage(content=(
        "你是一个严谨的金融 SQL 侦探。\n"
        "1. 必须使用 `execute_sql` 获取数据，严禁幻觉。\n"
        "2. 严格遵守 sqlite_master 查到的表名，不要加复数 s。"
        f"{correction_prompt}"
    ))

    # 4. 构造输入：系统指令 + 历史记录
    # 限制历史记录长度，防止 Token 爆炸导致响应变慢
    input_msgs = [sys_instruction] + messages[-10:]

    try:
        # 执行推理
        print("🤔 侦探正在思考并查阅账本...")
        response = await llm_with_tools.ainvoke(input_msgs)
        return {"messages": [response]}
    except Exception as e:
        # 万一崩溃，给个出口，不让程序卡死
        return {"messages": [AIMessage(content=f"❌ 侦探大脑思考时发生意外: {str(e)}")]}