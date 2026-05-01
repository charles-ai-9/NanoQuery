# NanoQuery 项目 LangChain/LangGraph 知识点全景总结

> 本文档系统梳理 NanoQuery 项目中所用到的 LangChain 生态核心组件/API。

---

## 目录

1. [LangGraph 核心概念](#1-langgraph-核心概念)
2. [State 状态管理](#2-state-状态管理)
3. [节点（Node）设计模式](#3-节点node设计模式)
4. [边与路由（Edge & Routing）](#4-边与路由edge--routing)
5. [工具调用（Tool Use / ReAct 模式）](#5-工具调用tool-use--react-模式)
6. [子图（Subgraph）](#6-子图subgraph)
7. [Human-in-the-Loop（HITL）](#7-human-in-the-loophitl)
8. [Memory 与 Store API](#8-memory-与-store-api)
9. [LLM 客户端封装](#9-llm-客户端封装)
10. [结构化输出（Structured Output）](#10-结构化输出structured-output)
11. [混合检索 RAG（Hybrid RAG）](#11-混合检索-raghybrid-rag)
12. [容错与重试机制（RetryPolicy）](#12-容错与重试机制retrypolicy)
13. [LangGraph Studio / Dev Server](#13-langgraph-studio--dev-server)
14. [项目整体架构图](#14-项目整体架构图)

---

## 1. LangGraph 核心概念

### 什么是 LangGraph？
LangGraph 是 LangChain 团队推出的**有状态、可循环的 AI 工作流编排框架**。它把 AI Agent 的运行流程建模为一张**有向图（DAG + 循环）**，每个节点是一个处理步骤，边定义了流程跳转规则。

### 核心三要素
| 要素 | 类比 | 项目中的体现 |
|------|------|-------------|
| **State（状态）** | 所有节点共享的"账本" | `MessagesState`，贯穿整个图 |
| **Node（节点）** | 具体干活的"探员" | `intent_node`, `generate_sql_node` 等 |
| **Edge（边）** | 节点之间的"走廊" | `add_edge`, `add_conditional_edges` |

### 图的生命周期

```python
# graph.py 中的标准四步法
builder = StateGraph(MessagesState)   # 1. 创建图蓝图
builder.add_node(...)                 # 2. 注册节点
builder.add_edge(...)                 # 3. 连接边
graph = builder.compile(...)          # 4. 编译成可执行对象
```

---

## 2. State 状态管理

### Pydantic BaseModel 作为 State

项目使用 **Pydantic `BaseModel`** 而非简单的 `TypedDict` 来定义状态，好处是：
- 自动类型校验（传错类型直接报错）
- 支持默认值，防止空指针
- IDE 友好，有代码提示

```python
# state.py
from pydantic import BaseModel, Field
from langgraph.graph import add_messages

class MessagesState(BaseModel):
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    route: str = Field(default="")
    data_freshness: str = Field(default="")
    sql_result: str = Field(default="")
    analysis: str = Field(default="")
```

### `add_messages` Reducer（归约器）

`add_messages` 是 LangGraph 内置的**消息归约函数**，它的作用是：
- **智能追加**：新消息会追加到列表末尾，而不是覆盖
- **去重覆盖**：如果新消息的 `id` 与已有消息相同，则覆盖（用于修正 tool call 结果）
- 用 `Annotated[List[BaseMessage], add_messages]` 语法声明

```python
# 每个节点只需返回字典，LangGraph 自动调用 add_messages 合并
return {"messages": [AIMessage(content="你好")]}
# 不需要手动处理 state.messages.append(...)
```

### 不同节点的状态共享

所有节点接收同一个 `state` 对象，节点返回的字典会被**合并**回 State 中：

```python
# 节点返回局部更新，不需要返回完整 State
async def some_node(state: MessagesState):
    return {"route": "business"}   # 只更新 route 字段
```

---

## 3. 节点（Node）设计模式

### 异步节点（async def）

项目中所有核心节点均为 **`async def`**，原因：
- LangGraph Studio 要求工具调用必须是异步的，否则会阻塞事件循环
- 大模型调用（`.ainvoke()`）是 I/O 密集型，异步可大幅提升并发性能

```python
async def intent_node(state: MessagesState, config: RunnableConfig, store: BaseStore):
    res = await _llm.ainvoke([...])
    return {"messages": [res], "route": "business"}
```

### 节点函数签名的"魔法参数"

LangGraph 会**自动注入**以下特殊参数，只要函数签名中声明了它们：

| 参数 | 类型 | 作用 |
|------|------|------|
| `state` | `MessagesState` | 当前状态（必须，位置第一） |
| `config` | `RunnableConfig` | 运行时配置（如用户名、角色权限） |
| `store` | `BaseStore` | 跨线程持久化存储（长期记忆） |

```python
async def intent_node(state: MessagesState, config: RunnableConfig, store: BaseStore):
    user_name = config.get("configurable", {}).get("user_name", "Jack")
    # config 包含调用时传入的动态配置，如：graph.ainvoke(input, config={"configurable": {"user_name": "Alice"}})
```

### `@lru_cache` 单例模式

用 Python 内置 `functools.lru_cache` 实现"懒加载单例"，避免重复初始化大模型：

```python
@lru_cache(maxsize=1)
def get_llm_with_tools():
    _llm = get_llm()
    return _llm.bind_tools([execute_sql, search_knowledge_base])
# 第一次调用时初始化，之后所有调用返回同一个实例
```

---

## 4. 边与路由（Edge & Routing）

### 普通边（add_edge）

固定的、无条件跳转：

```python
builder.add_edge(START, "intent")          # 图入口，固定跳转
builder.add_edge("check_freshness", "generate_sql")  # 哨兵完成后必去大脑
builder.add_edge("rca_subgraph", END)      # 子图完成后结束
```

### 条件边（add_conditional_edges）

根据路由函数的返回值**动态决定**下一跳：

```python
builder.add_conditional_edges(
    "intent",           # 源节点
    intent_router,      # 路由函数（返回字符串 key）
    {
        END: END,
        "generate_sql": "generate_sql",
        "check_freshness": "check_freshness",
        "rca_subgraph": "rca_subgraph"
    }
)
```

路由函数的写法：

```python
def intent_router(state: MessagesState):
    route = state.route           # 读取 State 中的路由标签
    if route == "chat":
        return END                # 返回 END 表示结束
    if route == "meta":
        return "generate_sql"     # 返回节点名字符串
    return "check_freshness"      # 默认兜底
```

### `tools_condition`（内置工具路由）

LangGraph 官方提供的**特殊条件路由函数**，专门用于 ReAct 循环：

```python
from langgraph.prebuilt import tools_condition

builder.add_conditional_edges(
    "generate_sql",
    tools_condition,   # 自动检测最后一条消息是否含有 tool_calls
    # 有 tool_calls → 跳到 "tools" 节点
    # 没有 tool_calls → 跳到 END
)
```

---

## 5. 工具调用（Tool Use / ReAct 模式）

### `@tool` 装饰器

将普通 Python 函数包装成 LangChain 可调度的工具：

```python
from langchain_core.tools import tool

@tool
async def execute_sql(query: str) -> str:
    """在 mock_data.db 上执行只读 SELECT SQL 查询并返回结果。"""
    return await asyncio.to_thread(_run_sql, query)
```

> ⚠️ **关键**：`docstring` 就是工具的描述，大模型会读它来决定何时调用该工具。写得越清晰，大模型调用越准确！

### `bind_tools`：给大模型挂载工具

```python
llm_with_tools = llm.bind_tools([execute_sql, search_knowledge_base])
# 之后调用 llm_with_tools.invoke()，大模型就"知道"这两个工具的存在
# 当它需要时，会在回复中附上 tool_calls 字段
```

### `ToolNode`（官方工具执行节点）

LangGraph 提供的开箱即用的工具执行节点，自动处理 `tool_calls` → 执行 → 返回 `ToolMessage`：

```python
from langgraph.prebuilt import ToolNode

builder.add_node("tools", ToolNode([execute_sql, search_knowledge_base]))
# 当 generate_sql 节点产生 tool_calls 时，ToolNode 自动：
# 1. 解析 tool_calls 中的工具名和参数
# 2. 调用对应的工具函数
# 3. 把结果封装成 ToolMessage 写回 messages
```

### ReAct 循环（Reasoning + Acting）

项目的核心执行模式，形成**大脑↔工具**的闭环：

```
generate_sql → tools_condition → tools → generate_sql → ...
                ↓ (没有 tool_calls)
               END
```

1. `generate_sql_node` 让大模型思考并生成 SQL，附带 `tool_calls`
2. `tools_condition` 检测到 `tool_calls`，跳转到 `tools` 节点
3. `ToolNode` 执行 SQL，将结果写入 `messages`（`ToolMessage`）
4. 流程回到 `generate_sql_node`，大模型读取结果，决定是否继续调用工具或结束

### 同步工具的异步化

SQLite 是同步阻塞操作，直接在异步函数中调用会阻塞事件循环。解决方案：

```python
import asyncio

@tool
async def execute_sql(query: str) -> str:
    # asyncio.to_thread 将同步函数放到线程池中执行，不阻塞主事件循环
    return await asyncio.to_thread(_run_sql, query)
```

---

## 6. 子图（Subgraph）

### 什么是子图？

子图是一个**独立编译的小图**，可以作为父图中的一个普通节点被挂载。适合把复杂的多步骤逻辑封装成模块。

```python
# rca_graph.py：独立定义并编译子图
def build_rca_subgraph() -> CompiledStateGraph:
    sg = StateGraph(RcaState)           # 子图有自己的 State
    sg.add_node("rca_analyse_node", rca_analyse_node)
    sg.set_entry_point("rca_analyse_node")
    sg.add_edge("rca_analyse_node", END)
    return sg.compile()

rca_graph = build_rca_subgraph()
```

```python
# graph.py：把子图当普通节点挂载
builder.add_node("rca_subgraph", rca_graph)  # 子图直接作为节点
builder.add_edge("rca_subgraph", END)
```

### 子图的 State 隔离与通信

- 子图有**自己独立的 State 类**（`RcaState`），与父图的 `MessagesState` 相互隔离
- 父图通过在父 State 中预留对应字段（如 `sql_result`、`analysis`）与子图通信
- LangGraph 在边界处自动做**字段名映射**（同名字段自动传递）

---

## 7. Human-in-the-Loop（HITL）

### `interrupt_before`：物理打断

在指定节点**执行前**挂起整个图，等待人类干预：

```python
from langgraph.checkpoint.memory import MemorySaver

memory = MemorySaver()
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["tools"]    # 在 tools 节点执行前暂停
)
```

### Checkpointer（检查点）

HITL 的基础设施。每次图执行到一个节点，`MemorySaver` 会把**当前完整 State 快照**保存到内存（或数据库）中：

```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
# 生产环境可换成 SqliteSaver 或 PostgresSaver 实现持久化
```

### 人类反馈闭环

```
用户提问 → generate_sql → [interrupt_before tools] → 人类审核/修改 SQL
       ↓                                                     ↓
    继续执行                                        追加 HumanMessage（修改意见）
       ↓                                                     ↓
    tools                                         回到 generate_sql 重新生成
```

在 `generate_sql_node` 中识别人类反馈：

```python
last_msg = messages[-1]
if isinstance(last_msg, HumanMessage):
    # 最后一条是人类追加的，说明是 HITL 干预反馈
    correction_prompt = f"[人类导师反馈]: {last_msg.content}。请根据反馈重新修正你的 SQL。"
```

---

## 8. Memory 与 Store API

### 两种记忆类型对比

| 类型 | 机制 | 作用范围 | 项目中的体现 |
|------|------|---------|------------|
| **短期记忆** | `messages` 列表 + `add_messages` | 单次会话（单个 thread） | `MessagesState.messages` |
| **长期记忆** | `Store API`（跨线程持久化） | 跨多次会话 | 用户偏好存储 |

### Store API 使用模式

```python
# 节点函数声明 store 参数，LangGraph 自动注入
async def intent_node(state: MessagesState, config: RunnableConfig, store: BaseStore):

    # 1. 定义命名空间（类似目录路径，用元组）
    namespace = ("user_profiles", user_name)   # ("分类", "用户ID")

    # 2. 写入（异步）
    await store.aput(namespace, "preference", {"likes": "喜欢喝咖啡"})
    #                              ↑ key       ↑ value（任意字典）

    # 3. 读取（异步）
    profile = await store.aget(namespace, "preference")
    if profile:
        data = profile.value    # 取出存储的字典
```

### `with_structured_output`（结构化记忆提取）

用 Pydantic 模型约束大模型的输出格式，自动提取用户偏好：

```python
from pydantic import BaseModel, Field

class UserMemory(BaseModel):
    has_preference: bool = Field(description="用户是否表达了个人特征？")
    preference_content: str = Field(description="提取的具体内容")

memory_extractor = _llm.with_structured_output(UserMemory)
result = await memory_extractor.ainvoke([...])
# result 是一个 UserMemory 实例，可以直接用 result.has_preference
```

---

## 9. LLM 客户端封装

### 双模式切换（本地 / 云端）

通过环境变量 `LLM_MODE` 动态切换大模型后端，代码层面使用统一接口：

```python
mode = os.getenv("LLM_MODE", "local").lower()

if mode == "cloud":
    # 通义千问（DashScope 协议）
    from langchain_community.chat_models.tongyi import ChatTongyi
    _llm_instance = ChatTongyi(model=model_name, ...)
else:
    # 本地/兼容 OpenAI 接口
    from langchain_openai import ChatOpenAI
    _llm_instance = ChatOpenAI(model=model_name, base_url=api_base, ...)
```

### 自动加载 `.env`

`llm_client.py` 在模块顶层主动加载环境变量，解决 LangGraph Studio 绕过 `main.py` 导致 `.env` 未加载的问题：

```python
from pathlib import Path
from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=_project_root / ".env", override=True)
# 无论谁导入此模块，.env 都会被加载
```

### Streaming 流式输出

```python
_llm_instance = ChatTongyi(
    model=model_name,
    streaming=True    # 开启流式，LangGraph Studio 可实时看到 token 输出
)
```

---

## 10. 结构化输出（Structured Output）

### `with_structured_output`

强制大模型按照 Pydantic 模型的 Schema 输出 JSON，并自动解析成 Python 对象：

```python
class UserMemory(BaseModel):
    has_preference: bool
    preference_content: str

extractor = llm.with_structured_output(UserMemory)
result: UserMemory = await extractor.ainvoke(messages)
print(result.has_preference)        # True/False，类型安全
print(result.preference_content)    # 字符串
```

**原理**：LangGraph 将 Pydantic 类转换为 JSON Schema，以 `function_call` 或 `tool_use` 的方式发给大模型，强制其按格式填写。

---

## 11. 混合检索 RAG（Hybrid RAG）

### 整体架构

```
用户问题
    ↓
search_knowledge_base（@tool）
    ↓
KnowledgeBase.query()
    ↓
EnsembleRetriever（RRF 融合）
   ├── FAISS 向量检索（语义相似度）
   └── BM25 关键词检索（词频统计）
    ↓
返回最相关文档片段给大模型
```

### FAISS 向量数据库

```python
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    cache_folder="data/models"          # 离线缓存，不重复下载
)

# 构建索引
vector_db = FAISS.from_documents(chunks, embeddings)
vector_db.save_local("data/vector_db")  # 持久化到磁盘

# 加载索引
vector_db = FAISS.load_local("data/vector_db", embeddings, allow_dangerous_deserialization=True)
```

### BM25 关键词检索

```python
from langchain_community.retrievers import BM25Retriever

bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = 2    # 返回前 2 个结果
```

### 混合检索融合（RRF 算法）

**互惠排名融合（Reciprocal Rank Fusion）** 将两路检索结果按排名打分并合并：

```python
# 每个文档的 RRF 分数 = Σ(weight × 1/(k + rank + 1))
rrf_k = 60    # 业界通用常数，用于平滑排名分布

for rank, doc in enumerate(retriever_docs):
    rrf_score = weight × (1.0 / (rrf_k + rank + 1))
    scores[doc_id] += rrf_score
```

### 文本切片

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,     # 每个块最多 500 字符
    chunk_overlap=50    # 相邻块重叠 50 字符，防止知识断层
)
chunks = splitter.split_documents(docs)
```

---

## 12. 容错与重试机制（RetryPolicy）

LangGraph 内置的**指数退避重试**，专门应对大模型 API 的偶发网络错误：

```python
from langgraph.types import RetryPolicy

network_armor = RetryPolicy(
    initial_interval=2.0,   # 首次失败等 2 秒
    backoff_factor=2.0,     # 指数退避：2s → 4s → 8s
    max_attempts=3          # 最多重试 3 次
)

# 在注册节点时挂载，只对高风险节点使用
builder.add_node("intent", intent_node, retry_policy=network_armor)
builder.add_node("generate_sql", generate_sql_node, retry_policy=network_armor)
```

---

## 13. LangGraph Studio / Dev Server

### `langgraph.json` 配置文件

LangGraph Studio 的入口配置，指定图的位置和 Python 环境：

```json
{
  "graphs": {
    "agent": "./src/agent/graph.py:build_graph"
  },
  "python_version": "3.11",
  "dependencies": ["."]
}
```

### `build_graph` 函数签名要求

LangGraph Dev Server（新版 `0.7.x+`）要求 `build_graph` 函数**不能有非标准参数**：

```python
# ✅ 正确：无参数 或 接受 RunnableConfig
def build_graph():
    ...

# ❌ 错误：带有自定义参数会导致 GraphLoadError
def build_graph(some_arg, another_arg):
    ...
```

### `RunnableConfig` 在运行时传递动态配置

```python
# 调用图时传入运行时配置
config = {
    "configurable": {
        "thread_id": "session_001",      # Checkpointer 用于区分会话
        "user_name": "Alice",            # 自定义业务字段
        "role": "admin"
    }
}
graph.ainvoke({"messages": [HumanMessage(content="你好")]}, config=config)
```

---

## 14. 项目整体架构图

```
用户输入 (HumanMessage)
        │
        ▼
   ┌─────────────┐
   │  intent_node │  ← 物理关键词拦截 + LLM 意图分类 + 长期记忆存取
   └──────┬──────┘
          │ intent_router（条件路由）
    ┌─────┴──────┬──────────────┬──────────┐
    ▼            ▼              ▼          ▼
  [END]    check_freshness   rca_subgraph  generate_sql
 (闲聊)        (哨兵)         (子图：RCA)      │
                │                          │ tools_condition
                └──────────────────────────►  (ReAct 循环)
                                           │
                              ┌────────────┴──────────────┐
                              ▼                           ▼
                           [END]                      tools (ToolNode)
                         (输出结果)              ┌──────────────────┐
                                                │  execute_sql      │
                                                │  search_knowledge │
                                                └──────────────────┘
                                                         │
                                              ←──────────┘ (ToolMessage 回写)
```

### 核心数据流

```
HumanMessage → AIMessage (tool_calls) → ToolMessage (结果) → AIMessage (最终回复)
```

---

## 知识点速查表

| 知识点 | 所在文件 | LangChain/LangGraph API |
|--------|---------|------------------------|
| 图定义与编译 | `graph.py` | `StateGraph`, `compile()` |
| 状态管理 | `state.py` | `BaseModel`, `add_messages`, `Annotated` |
| 意图路由 | `graph.py` | `add_conditional_edges`, `END` |
| ReAct 工具循环 | `graph.py` | `ToolNode`, `tools_condition` |
| 工具定义 | `sql_tools.py` | `@tool` |
| 工具绑定 | `nodes.py` | `llm.bind_tools()` |
| 结构化输出 | `nodes.py` | `llm.with_structured_output()` |
| 长期记忆 | `nodes.py` | `BaseStore`, `store.aput()`, `store.aget()` |
| 运行时配置 | `nodes.py` | `RunnableConfig`, `config.get("configurable")` |
| 子图 | `rca_graph.py` | `StateGraph`, `CompiledStateGraph` |
| 重试策略 | `graph.py` | `RetryPolicy` |
| 人工干预 | `graph.py` | `MemorySaver`, `interrupt_before` |
| 环境自加载 | `llm_client.py` | `load_dotenv()`, `pathlib.Path` |
| 混合检索 | `vector_store.py` | `FAISS`, `BM25Retriever`, `HuggingFaceEmbeddings` |
| 文本切片 | `vector_store.py` | `RecursiveCharacterTextSplitter` |
| 流式输出 | `llm_client.py` | `streaming=True` |
| Unicode 修复 | `graph.py` | `sys.stdout.reconfigure(encoding="utf-8")` |

