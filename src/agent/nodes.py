import logging
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command
from .state import MessagesState
from src.tools.sql_tools import execute_sql
from functools import lru_cache
from src.core.llm_client import get_llm
from langgraph.store.base import BaseStore  # 用于类型提示
from pydantic import BaseModel, Field
from src.tools.sql_tools  import search_knowledge_base

logger = logging.getLogger(__name__)

llm = None
llm_with_tools = None

# ================== 知识库单例延迟加载，彻底消除循环依赖 ==================
# 不在模块顶层实例化，改为按需加载
@lru_cache(maxsize=1)
def get_kb_instance():
    """获取 KnowledgeBase 单例，并确保索引已加载"""
    from src.core.vector_store import KnowledgeBase  # 延迟导入，避免循环依赖
    kb = KnowledgeBase()
    if not kb.load_index():
        kb.build_index()
    return kb
# ========================================================================

@lru_cache(maxsize=1)
def get_llm_with_tools():
    """获取挂载了工具的大模型单例实例"""
    _llm = get_llm()
    if _llm is None:
        raise ValueError("❌ 大模型初始化失败，请检查环境变量配置！")
    return _llm.bind_tools([execute_sql, search_knowledge_base])

def initialize_llm(llm_instance):
    """兼容旧接口：初始化全局 llm 和 llm_with_tools"""
    global llm, llm_with_tools
    llm = llm_instance
    llm_with_tools = llm.bind_tools([execute_sql])

class UserMemory(BaseModel):
    has_preference: bool = Field(description="用户是否在这句话中明确表达了个人喜好、习惯、身份或人物特征？")
    preference_content: str = Field(description="如果表达了特征，请提取具体内容(精简为短语，如'喜欢喝咖啡'、'我是审计部的')；如果没有，返回空字符串。")

async def intent_node(state: MessagesState, config: RunnableConfig, store: BaseStore):
    user_name = config.get("configurable", {}).get("user_name", "Jack")
    user_role = config.get("configurable", {}).get("role", "admin")
    if not state.messages:
        logger.warning("intent_node: 消息列表为空，直接路由到 chat")
        return {"route": "chat"}
    last_msg_content = state.messages[-1].content.strip()
    _llm = get_llm()
    if _llm is None:
        error_msg = "❌ 大模型初始化失败，请检查 .env 文件配置。"
        logger.error("intent_node: %s", error_msg)
        return {"messages": [AIMessage(content=error_msg)], "route": "chat"}
    ## LangGraph 强制要求用元组做 Namespace。 用元组是Python语言体系的一个设计套路，类似于目录层级结构。
    namespace = ("user_profiles", user_name)
    ## 强行约束大模型，让它必须、只能、且完美地按照 UserMemory 这个类定义的格式返回数据。
    ## 自动把 UserMemory 的结构转换成大模型能听懂的“函数定义”或“JSON Schema”发过去
    memory_extractor = _llm.with_structured_output(UserMemory)
    try:
        memory_result = await memory_extractor.ainvoke([
            SystemMessage(
                content="你是一个心理分析师，任务是从用户的日常对话中提取他们的长期偏好或个人特征。如果没有明确特征，不要凭空捏造。"),
            HumanMessage(content=last_msg_content)
        ])
        if memory_result and memory_result.has_preference and memory_result.preference_content:
            ## .aput = Asynchronous Put 异步”操作
            await store.aput(namespace, "preference", {"likes": memory_result.preference_content})
            ## 结构化后的数据方便我们直接拿来用：memory_result.preference_content
            logger.info(f"💾 [Store API]: 智能提取并持久化特征 -> [{memory_result.preference_content}]")
    except Exception as e:
        logger.warning(f"记忆提取环节发生异常 (非致命，跳过): {e}")
    profile = await store.aget(namespace, "preference")

   #================================= 物理拦截模式（快通道）：基于关键词的硬规则优先级最高 =================================
    known_preference = profile.value.get("likes") if profile else None
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
    # ===============================大模型（慢通道）====================================================

    system_prompt = """你是一个极其严谨的星际金融风控局前台接待员（意图路由器）。
        请严格根据用户的输入，将其划分到以下四个意图之一：

        1. 【BUSINESS】（业务数据与知识查询）🎯：
           - 当用户询问具体的业务数据（如“有多少客户”、“逾期金额是多少”）。
           - 当用户询问金融风控术语（如“什么是 DPD”、“解释一下 M1/M2”）。
           - 当用户询问公司内部政策、规章制度、催收操作手册（如“M2的惩罚策略是什么”）。
           ⚠️ 极其重要：所有名词解释、政策查询，一律归为 BUSINESS！

        2. 【ANALYSIS】（根因与异常分析）📉：
           - 当用户发现某个指标发生异动，要求查明原因时（如“为什么上个月的坏账率突然升高了”、“帮我排查一下订单量下降的归因”）。
           ⚠️ 注意：不要把简单的名词“解释”归类为“分析”！

        3. 【META】（数据库元数据）📊：
           - 当用户询问数据库表结构、有哪些表、字段代表什么意思时。

        4. 【CHAT】（闲聊与问候）☕：
           - 日常打招呼、夸奖、或者与金融风控无关的闲聊。

        回复格式要求：如果是 CHAT，回复 【CHAT】+ 一句符合探员身份的幽默回应；如果是其他三类，请严格只回复【标签名】（如 【BUSINESS】），绝不要输出任何其他字符！"""
    res = await _llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg_content)])
    res_text = res.content.upper()
    logger.info("intent_node: LLM 分类结果 → %s", res_text[:50])

    if "CHAT" in res_text:
        reply = res.content.replace("【CHAT】", "").strip()
        ## 在闲聊的情况下，如果之前记忆里提取到了用户的偏好特征，就把它优雅地融入回复里，增加个性化和温度。
        if known_preference:
            personalized_reply = f"[权限: {user_role}] 敬礼！{user_name}！我知道您【{known_preference}】！{reply}"
        else:
            personalized_reply = f"[权限: {user_role}] 敬礼！{user_name}！{reply}"
        return {"messages": [AIMessage(content=personalized_reply)], "route": "chat"}
    elif "META" in res_text:
        return {"messages": [res], "route": "meta"}
    elif "ANALYSIS" in res_text:
        return {"messages": [res], "route": "analysis"}
    else:
        return {"messages": [res], "route": "business"}

async def check_data_freshness_node(state: MessagesState):
    date = "2024-12-23"
    return {"messages": [SystemMessage(content=f"当前数据截止到 {date}。")], "data_freshness": date}

async def generate_sql_node(state: MessagesState, config: RunnableConfig):
    _llm_with_tools = get_llm_with_tools()

    ## 可以根据 config 里的用户信息动态调整提示词，增强个性化和安全性。「在每个节点都可以用到」
    user_name = config.get("configurable", {}).get("user_name", "未知员工")
    user_role = config.get("configurable", {}).get("role", "user")

    messages = state.messages
    last_msg = messages[-1] if messages else None
    last_msg_content = last_msg.content if last_msg else ""

    correction_prompt = ""

    # 情景A：人类导师反馈纠错
    # isinstance(last_msg, HumanMessage)：最后一条消息必须是人类发出的。
    if isinstance(last_msg, HumanMessage) and len(messages) > 1:
        correction_prompt = (
            "\n[👨‍💼 人类导师反馈]\n"
            f"反馈内容：{last_msg_content}\n"
            "请仔细阅读上述人类反馈修正 SQL。如果提供了完整 SQL 则原封不动执行。"
        )

    # 情景B：系统级物理纠错
    elif "ERROR" in last_msg_content:
        correction_prompt = (
            "\n[🚩 紧急纠错指令]\n"
            f"错误信息为: {last_msg_content}\n"
            "请分析原因修正 SQL 后再次调用。"
        )

    role_instruction = ""
    if user_role == "admin":
        role_instruction = f"3. 【权限最高级】：当前操作者是 {user_name} (Admin)，拥有所有数据库表的无限制查询权限。"
    else:
        role_instruction = f"3. 【权限受限】：当前操作者是 {user_name} ({user_role})，生成的 SQL 必须严格限制范围，严禁查询薪酬、密码等高管敏感表！"

    sys_instruction = SystemMessage(content=(
        "你是一个严谨的金融 SQL 侦探。\n"
        "1. 严禁幻觉：必须且只能使用 `execute_sql` 获取数据。\n"
        "2. 命名规范：严格遵守数据库表名，SQLite 中不要随意加复数 's'。\n"
        f"{role_instruction}\n"
        f"{correction_prompt}"
    ))

    input_msgs = [sys_instruction] + messages[-10:]
    try:
        logger.info(f"generate_sql_node: 正在调度 AI... [当前权限: {user_role}]")
        response = await _llm_with_tools.ainvoke(input_msgs)
        return {"messages": [response]}
    except Exception as e:
        logger.error("大脑节点崩溃: %s", str(e))
        return {"messages": [AIMessage(content=f"❌ 侦探大脑思考时发生意外: {str(e)}")]}