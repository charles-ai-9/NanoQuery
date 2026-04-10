import logging
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
# 注意这里的导入路径，按你实际项目结构调整
from .state import MessagesState
from src.tools.sql_tools import execute_sql
from functools import lru_cache
from src.core.llm_client import get_llm

logger = logging.getLogger(__name__)

llm = None
llm_with_tools = None


@lru_cache(maxsize=1)
def get_llm_with_tools():
    """获取挂载了工具的大模型单例实例"""
    _llm = get_llm()
    if _llm is None:
        raise ValueError("❌ 大模型初始化失败，请检查环境变量配置！")
    return _llm.bind_tools([execute_sql])


def initialize_llm(llm_instance):
    """兼容旧接口：初始化全局 llm 和 llm_with_tools"""
    global llm, llm_with_tools
    llm = llm_instance
    llm_with_tools = llm.bind_tools([execute_sql])


async def intent_node(state: MessagesState):
    """
    【前台探员】：负责意图识别与流量调度。
    """

    # ── 第一道防线：消息为空检查 ──────────────────────────────────────────
    # 🛠️ 探长改造点 1：不再用 state.get("messages")，直接用 state.messages
    # 因为 Pydantic 保证了即便没数据，它也是个空列表 []，绝不会报错
    if not state.messages:
        logger.warning("intent_node: 消息列表为空，直接路由到 chat")
        return {"route": "chat"}

    # 🛠️ 探长改造点 2：不再用 state["messages"]，直接用点语法
    last_msg_content = state.messages[-1].content.strip()

    # ── 第二道防线：关键字物理拦截（不依赖 LLM）────────────────────────────
    META_KEYWORDS = ["表", "字段", "结构", "元数据", "有哪些表", "schema"]
    ANALYSIS_KEYWORDS = ["为什么", "原因", "分析", "归因", "排查"]

    for kw in META_KEYWORDS:
        if kw in last_msg_content:
            logger.info("intent_node: 关键字[%s]触发物理拦截 → meta", kw)
            return {"messages": [AIMessage(content="【META】")], "route": "meta"}

    for kw in ANALYSIS_KEYWORDS:
        if kw in last_msg_content:
            logger.info("intent_node: 关键字[%s]触发物理拦截 → analysis", kw)
            return {"messages": [AIMessage(content="【ANALYSIS】")], "route": "analysis"}

    # ── 第三道防线：LLM 初始化检查 ─────────────────────────────────────────
    _llm = get_llm()
    if _llm is None:
        error_msg = "❌ 大模型初始化失败，请检查 .env 文件路径及 OPENAI_API_KEY 配置是否正确。"
        logger.error("intent_node: %s", error_msg)
        return {"messages": [AIMessage(content=error_msg)], "route": "chat"}

    # ── 第四道防线：LLM 意图分类（正常路径）────────────────────────────────
    system_prompt = """你是一个极其严谨的金融数据库侦探前台。
    请根据用户的输入进行分类。**严禁**将涉及数据库结构的询问误判为闲聊。

    分类准则：
    1. 【META】：询问数据库里有什么表、表里有什么字段、查看表结构、查询元数据。
       - 示例："系统里有哪些表？"、"user表结构是什么？"、"帮我查下元数据"。
    2. 【BUSINESS】：查询具体的金融指标、逾期金额、资产数据、用户具体信息。
       - 示例："查下张三的余额"、"去年逾期总额是多少？"。
    3. 【ANALYSIS】：询问原因、做归因分析、问"为什么"。
       - 示例："为什么这笔贷款逾期了？"、"分析下坏账原因"。
    4. 【CHAT】：仅限纯粹的打招呼、心情分享或完全不涉及数据库意图的闲聊。
       - **特殊指令**：如果用户的问题中包含"表"、"字段"、"查"、"数据"等词汇，**必须**分类为 META 或 BUSINESS，严禁进入 CHAT。

    回复格式要求：
    - 如果是 CHAT：回复 【CHAT】+ 幽默回复。
    - 其他情况：只回复单单词 【META】、【BUSINESS】 或 【ANALYSIS】，不要有任何废话。"""

    res = await _llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg_content)])
    res_text = res.content.upper()
    logger.info("intent_node: LLM 分类结果 → %s", res_text[:50])

    if "CHAT" in res_text:
        reply = res.content.replace("【CHAT】", "").strip()
        return {"messages": [AIMessage(content=reply or "您好！")], "route": "chat"}
    elif "META" in res_text:
        return {"messages": [res], "route": "meta"}
    elif "ANALYSIS" in res_text:
        return {"messages": [res], "route": "analysis"}
    else:
        return {"messages": [res], "route": "business"}


async def check_data_freshness_node(state: MessagesState):
    """
    【哨兵探员】：负责环境感知。
    """
    date = "2024-12-23"
    # 💡 架构师笔记：返回依然是字典！LangGraph 会自动把这个字典丢进 Pydantic 里做校验。
    return {"messages": [SystemMessage(content=f"当前数据截止到 {date}。")], "data_freshness": date}


async def generate_sql_node(state: MessagesState):
    """
    【核心大脑】：ReAct 思想的物理载体。
    """
    _llm_with_tools = get_llm_with_tools()

    # 🛠️ 探长改造点 3：不再用 state["messages"]，直接用点语法
    messages = state.messages
    last_msg = messages[-1] if messages else None
    last_msg_content = last_msg.content if last_msg else ""

    correction_prompt = ""

    # 场景 A：识别人类导师干预
    if isinstance(last_msg, HumanMessage) and len(messages) > 1:
        correction_prompt = (
            "\n[👨‍💼 人类导师反馈]\n"
            f"反馈内容：{last_msg_content}\n"
            "请仔细阅读上述人类反馈：\n"
            "1. 如果反馈是一段文字建议，请结合建议重新推理并修正你的 SQL。\n"
            "2. 如果反馈直接提供了一段完整的 SQL 代码，请**原封不动**地使用该 SQL 调用 `execute_sql`，严禁擅自修改。"
        )

    # 场景 B：识别工具执行报错
    elif "ERROR" in last_msg_content:
        correction_prompt = (
            "\n[🚩 紧急纠错指令]\n"
            f"侦探请注意：上一次尝试查询失败，错误信息为: {last_msg_content}\n"
            "请你分析原因（比如字段名猜错了、表名拼错了），修正 SQL 后再次调用 `execute_sql`。"
        )

    sys_instruction = SystemMessage(content=(
        "你是一个严谨的金融 SQL 侦探。\n"
        "1. 严禁幻觉：必须且只能使用 `execute_sql` 获取数据。\n"
        "2. 命名规范：严格遵守数据库表名，SQLite 中不要随意加复数 's'。\n"
        f"{correction_prompt}"
    ))

    # 只取最近 10 条消息，防止 Token 超限
    input_msgs = [sys_instruction] + messages[-10:]

    try:
        logger.info("generate_sql_node: 正在调度 AI 进行推理并决策...")
        response = await _llm_with_tools.ainvoke(input_msgs)
        return {"messages": [response]}
    except Exception as e:
        logger.error("大脑节点崩溃: %s", str(e))
        return {"messages": [AIMessage(content=f"❌ 侦探大脑思考时发生意外: {str(e)}")]}