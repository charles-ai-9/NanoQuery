# NanoQuery

NanoQuery 是一个基于 LangGraph 的金融侦探智能体项目，具备多轮对话、意图识别、SQL 生成与执行、哨兵数据水位自省、Copilot LLM 智能授权等能力。适用于金融风控、数据分析等场景。

## 主要特性
- 多轮对话与意图识别
- 智能 SQL 生成与执行
- 数据水位哨兵机制
- Copilot LLM 自动授权与热加载
- LangSmith 监控集成
- 支持本地 mock 数据与真实数据库

## 快速开始
1. 克隆项目

   ```bash
   git clone <repo-url> NanoQuery
   cd NanoQuery
   ```

2. 安装依赖

   ```bash
   pip install -r requirements.txt
   ```
3. 初始化数据库：
   ```bash
   python init_db.py
   ```
4. 配置 Copilot 授权（首次运行自动弹出 Device Flow 验证码）
5. 启动主程序：
   ```bash
   python main.py
   ```

## 目录结构

```bash
NanoQuery/
├── main.py
├── README.md
├── requirements.txt
├── data/
│   ├── __init__.py
│   ├── init_db.py
│   ├── finance_detective.db
│   └── ...
├── src/
│   ├── __init__.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   └── ...
│   └── ...
└── ...
```

## Copilot 授权说明
- 支持 ghu_ OAuth 令牌自动缓存与热加载
- 支持 Device Flow 浏览器授权
- Token 缓存于 `.copilot_token_cache` 文件

## 监控与追踪
- 支持 LangSmith 云端监控
- 可选集成 Langfuse 本地监控

## 适用场景
- 金融风控归因分析
- 智能 SQL 数据查询
- 多轮对话数据分析

---

如需详细文档与高级用法，请参考源码注释。

# LangGraph SQL Agent — 多智能体自纠错与归因分析系统

> 基于 **LangGraph 0.3.x** + **LangChain** 构建的生产级 SQL 智能体，
> 具备自纠错循环、人工审批中断、记忆注入和多智能体子图四大核心能力。

---

## 目录

- [项目简介](#项目简介)
- [技术架构](#技术架构)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [核心模块说明](#核心模块说明)
- [配置说明](#配置说明)
- [开发指南](#开发指南)

---

## 项目简介

本项目实现了一个具备以下能力的 LangGraph 智能体系统：

1. **自然语言 → SQL**：接收用户的自然语言查询，由 LLM 自动生成 SQL 语句
2. **自纠错引擎**：执行 SQL 时若捕获到错误，自动将错误信息反馈给 LLM 重新生成
3. **人工审批中断**：执行 `UPDATE / DELETE / DROP` 等危险操作前强制挂起，等待人工确认
4. **长期记忆注入**：通过 `InMemoryStore` 存储用户偏好，每次生成 SQL 前自动注入上下文
5. **归因分析子图**：SQL 执行成功后，由独立的 RCA 子图调用 LLM 对结果进行业务归因分析

---

## 技术架构

```
用户输入
   │
   ▼
[generate_sql_node] ◄─────────────────────────────────┐
   │  ↑ 从 InMemoryStore 注入 user_preferences        │
   │  ↑ 将 errors 拼入 Prompt 重试                    │
   ▼                                                   │
[execute_sql_node]  ← interrupt_before（危险 SQL 挂起）│
   │                                                   │
   ├─── 执行失败 ──► Command(goto="generate_sql_node") ┘
   │                   update={"errors": [...]}
   │
   ├─── 执行成功 ──► [rca_node]（归因分析子图）
   │                    │
   │                    ▼
   │               RcaState: sql_result → LLM → analysis
   │
   └──────────────────► END
```

**核心依赖：**

| 组件 | 用途 |
|------|------|
| `LangGraph 0.3.x` | 图编排、状态管理、中断、checkpointing |
| `LangChain Core` | LLM 抽象、消息类型、工具装饰器 |
| `langchain-openai` | ChatOpenAI（可选，支持降级） |
| `SQLite` | 本地数据库（mock 金融数据） |
| `MemorySaver` | 断点续跑状态持久化 |
| `InMemoryStore` | 跨会话用户偏好记忆存储 |

---

## 功能特性

### 阶段一：基础设施
- SQLite 数据库初始化，含 mock 金融贷款数据
- `AgentState` TypedDict 状态定义

### 阶段二：自纠错引擎
- `execute_sql` 异步工具，`try-except` 捕获所有 SQLite 异常，错误作为字符串返回
- `generate_sql_node` / `execute_sql_node` 双节点
- 失败时通过 `Command(goto=..., update=...)` 退回生成节点重试

### 阶段三：人工审批 + 记忆
- `interrupt_before=["execute_sql_node"]` 危险操作前挂起
- `MemorySaver` checkpointer 支持断点续跑
- `InMemoryStore` 存储 `user_preferences`，生成 SQL 前自动注入

### 阶段四：多智能体子图
- `rca_subgraph`：独立的 `StateGraph(RcaState)`，无 checkpointer
- 主图通过共享字段 `sql_result / analysis` 自动映射数据进出子图
- LLM 降级策略：无 API Key 时自动切换为 `FakeListChatModel`

---

## 快速开始

### 1. 克隆项目

```bash
git clone <repository-url>
cd NanoQuery
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量（可选）

```bash
export OPENAI_API_KEY="sk-..."
```

> **不配置也可运行。** 系统会自动降级为 `FakeListChatModel`，
> SQL 生成和归因分析均输出 Mock 内容，适合本地开发调试。

### 4. 初始化数据库

```bash
python -c "from data.init_db import init; init()"
```

### 5. 运行智能体

```bash
python main.py
```

---

## 项目结构

```
NanoQuery/
├── main.py                      # 入口：调用图、处理中断审批
├── data/
│   ├── init_db.py               # SQLite 数据库初始化 & mock 数据
│   └── finance_detective.db     # SQLite 数据库文件
└── src/
    └── agent/
        ├── state.py             # AgentState TypedDict 定义
        ├── tools.py             # execute_sql 异步工具
        ├── nodes.py             # generate_sql_node / execute_sql_node
        ├── graph.py             # StateGraph 编排、编译、checkpointer、store
        └── subgraphs/
            └── rca_graph.py     # 归因分析子图（RCA Subgraph）
```

---

## 核心模块说明

### `state.py` — 状态定义

```python
class AgentState(TypedDict):
    user_input   : str        # 用户自然语言输入
    sql          : str        # LLM 生成的 SQL
    sql_result   : str        # SQL 执行结果
    errors       : list[str]  # 历史错误信息，用于重试
    analysis     : str        # RCA 子图归因分析结果
    needs_approval: bool      # 是否需要人工审批
```

### `tools.py` — SQL 执行工具

- 异步 `@tool execute_sql(sql: str) -> str`
- 连接 `finance_detective.db`，执行查询，返回结果字符串
- 全部 `sqlite3` 异常被 `try-except` 捕获后以字符串形式返回，**不抛出异常**

### `nodes.py` — 图节点

| 节点 | 职责 |
|------|------|
| `generate_sql_node` | 查 Store 注入记忆 → 拼接 errors → 调用 LLM 生成 SQL |
| `execute_sql_node` | 检测危险词 → 调用 execute\_sql 工具 → 返回 Command |

### `graph.py` — 图编排

```python
builder.compile(
    checkpointer=MemorySaver(),
    store=InMemoryStore(),
    interrupt_before=["execute_sql_node"],
)
```

### `rca_graph.py` — 归因分析子图

- 独立 `StateGraph(RcaState)`，单节点 `rca_analyse_node`
- 无 checkpointer，由主图统一管理
- 共享字段 `sql_result / analysis` 自动映射

---

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `OPENAI_API_KEY` | 未设置 | 设置后启用真实 LLM，否则使用 Mock |

**危险 SQL 关键词**（触发 `interrupt_before`）：

```
UPDATE, DELETE, DROP, TRUNCATE, ALTER, INSERT
```

---

## 开发指南

### 本地调试（无 API Key）

所有 LLM 节点均内置 `FakeListChatModel` 降级，无需任何外部依赖即可完整运行图的全部分支。

### 添加新的归因子图

1. 在 `src/agent/subgraphs/` 下新建子图文件
2. 定义私有 `State` TypedDict，确保与主图共享字段同名
3. 调用 `sg.compile()`（不传 checkpointer）
4. 在 `graph.py` 中 `builder.add_node("new_node", new_subgraph)`

### 恢复中断的执行

```python
graph.invoke(
    None,
    config={"configurable": {"thread_id": "same-thread-id"}},
)
```

---

## License

MIT

---

# LangGraph 金融侦探 Copilot LLM 授权与集成方案

## 背景
本项目支持自动集成 GitHub Copilot LLM 算力，兼容多种开发环境（如 PyCharm、Copilot CLI、GitHub CLI、浏览器授权等），无需手动配置 .env 或 token，极大提升易用性和安全性。

## Copilot LLM 授权原理
- **Copilot LLM 只接受 OAuth token（ghu_ 或 tid_ 开头）**，而 GitHub PAT（ghp_、gho_）仅适用于 GitHub API，不适用于 Copilot LLM。
- 必须确保 LLM 初始化时只用 OAuth token，否则会报错：`Personal Access Tokens are not supported for this endpoint`。

## 自动提取与授权流程
1. **启动时环境变量清理**
   - 自动清除 `GITHUB_TOKEN`、`GITHUB_API_KEY`，防止 PAT 被 langchain 或 Copilot SDK 误用。

2. **多路径 token 提取**
   - 优先级顺序：
     1. PyCharm Copilot 插件配置（适配 JetBrains 授权场景）
     2. Copilot hosts.json（标准 Copilot CLI 授权缓存）
     3. GitHub CLI（`gh auth token`，兼容部分开发者习惯）
     4. Device Flow 浏览器授权（兜底，强制唤起浏览器手动授权）
   - 只要发现 PAT（ghp_、gho_），立即跳过并提示用户，绝不用于 LLM。

3. **Device Flow 授权**
   - 如果本地没有 OAuth token，自动发起 Device Flow，打印授权链接和验证码，用户在浏览器中手动授权，轮询获取 OAuth token。

4. **LLM 初始化防御**
   - 只有 token 以 ghu_ 或 tid_ 开头时，才允许初始化 ChatGitHubCopilot，否则提示用户重新授权。
   - 日志输出详细，便于用户定位授权问题。

5. **全流程无缝体验**
   - 用户无需手动配置 .env 或 token，系统自动提取、校验、授权，极大提升易用性和安全性。

## 代码实现要点
- 启动时清理环境变量，防止 PAT 干扰。
- 多路径自动提取 Copilot OAuth token，优先本地缓存，兜底浏览器授权。
- 只允许 Copilot OAuth token 初始化 LLM，PAT 会被自动忽略。
- 日志友好，用户体验佳。

## 适用场景
- 个人开发、企业内网、CI/CD、云端/本地多环境，均可无缝集成 Copilot LLM 算力。

## 常见问题
- **PAT 报错**：PAT（ghp_、gho_）无法用于 Copilot LLM，需用 OAuth token（ghu_、tid_）。
- **如何授权**：首次运行时会自动唤起浏览器授权，按提示操作即可。
- **无需 .env 配置**：无需手动配置 token，系统自动提取。

---
如需扩展，可将 token 缓存到本地，或支持更多 IDE 授权路径。
