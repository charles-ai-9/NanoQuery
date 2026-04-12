# NanoQuery 金融侦探智能体

NanoQuery 是一个基于 LangGraph 的多智能体金融风控对话系统，支持多轮意图识别、SQL 自动生成与执行、知识库混合检索（Hybrid RAG）、人工审批（HITL）、长期记忆等高级特性。适用于金融风控、数据分析、企业知识问答等场景。

---

## ⭐️ 主要特性
- 多轮对话与意图识别（支持 LLM+物理关键字双重路由）
- 智能 SQL 生成与自动执行（ReAct 循环，支持纠错）
- 数据水位哨兵机制（自动提示数据截止日期）
- Copilot/通义千问/自建 LLM 热切换与授权
- LangSmith/本地持久化监控与断点续跑
- 支持本地 mock 数据与真实数据库
- 自纠错 SQL 生成引擎（支持人类反馈闭环）
- 人工审批中断（HITL）与状态编辑
- 长期记忆注入（用户画像、偏好提取）
- 多智能体归因分析子图（RCA）
- 官方 Hybrid RAG 知识库（FAISS+BM25+RRF）

---

## 🗂️ 目录结构

```
NanoQuery/
├── main.py                  # CLI 主入口（本地运行/调试/HITL）
├── dev.py                   # LangGraph Studio 启动入口
├── requirements.txt         # 依赖清单
├── README.md                # 项目文档
├── rag_hybrid_search.md     # 混合检索原理说明
├── data/
│   ├── init_db.py           # mock 数据库初始化脚本
│   ├── mock_data.db         # mock SQLite 数据库
│   ├── knowledge/           # 业务知识库（.md 文档）
│   │   └── risk_control_handbook.md
│   ├── memory/              # 状态快照/长期记忆
│   │   └── nanoquery.db     # 持久化存储
│   ├── models/              # 本地嵌入模型缓存
│   │   └── models--sentence-transformers--all-MiniLM-L6-v2/
│   └── vector_db/           # FAISS 索引文件
│       ├── index.faiss
│       └── index.pkl
├── src/
│   ├── core/
│   │   ├── llm_client.py    # LLM 客户端（支持多云/本地切换）
│   │   └── vector_store.py  # 官方 Hybrid RAG 检索器
│   ├── agent/
│   │   ├── graph.py         # 主图编排（支持 HITL）
│   │   ├── nodes.py         # 业务节点逻辑
│   │   ├── state.py         # 状态类型定义
│   │   ├── subgraphs/
│   │   │   └── rca_graph.py # 归因分析子图
│   │   └── tools/
│   │       └── sql_tools.py # SQL 执行/知识库检索工具
└── ...
```

---

## 🚀 快速开始

1. **克隆项目**
   ```bash
   git clone <repo-url> NanoQuery
   cd NanoQuery
   ```
2. **创建虚拟环境**
   ```bash
   python -m venv nano_query_env
   source nano_query_env/bin/activate  # macOS/Linux
   # Windows: nano_query_env\Scripts\activate
   ```
3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```
4. **初始化数据库**
   ```bash
   python data/init_db.py
   ```
5. **配置 .env 环境变量**（详见下方说明）
6. **启动本地 CLI**
   ```bash
   python main.py
   ```
7. **启动 LangGraph Studio（可视化/云端）**
   ```bash
   langgraph dev
   ```

---

## ⚙️ 依赖说明
详见 requirements.txt，核心依赖：
- langchain, langchain-core, langchain-openai, langgraph
- langchain_community, langchain_text_splitters
- SQLAlchemy, pydantic, python-dotenv, requests
- huggingface, faiss-cpu, tqdm

---

## 🔑 环境变量配置（.env 示例）
```env
# LLM 选择（cloud=通义千问，local=自建OpenAI兼容）
LLM_MODE=cloud
# 通义千问云端
DASHSCOPE_API_KEY=sk-xxx
CLOUD_MODEL_NAME=qwen-max
# 本地OpenAI兼容
LOCAL_API_KEY=sk-xxx
LOCAL_API_BASE=http://localhost:8000/v1
LOCAL_MODEL_NAME=Qwen-7B-Chat
# OpenAI 兼容
OPENAI_API_KEY=sk-xxx
# LangSmith 监控
LANGCHAIN_API_KEY=ls-xxx
LANGCHAIN_PROJECT=NanoQuery
```

---

## 🧠 知识库混合检索（Hybrid RAG）
- **知识源**：`data/knowledge/*.md`（如 risk_control_handbook.md）
- **分词切片**：RecursiveCharacterTextSplitter（500/50）
- **向量检索**：FAISS + HuggingFaceEmbeddings（all-MiniLM-L6-v2，缓存至 data/models）
- **关键词检索**：BM25Retriever
- **融合算法**：EnsembleRetriever（RRF 互惠排名，权重 0.5/0.5）
- **索引落盘**：`data/vector_db/`
- **用法**：`KnowledgeBase().query("DPD")`，自动并行召回+排序

---

## 👨‍💼 人工审批（HITL）与状态编辑
- `graph.py` 配置 `interrupt_before=["tools"]`，SQL 执行前自动挂起
- 人类可直接编辑 State（如修改 tool_calls/query）并放行
- 支持追加 HumanMessage 反馈，AI 节点自动识别并纠错
- 详见 main.py CLI 审批流程

---

## 🛡️ 安全与合规
- 严格区分前后端输入校验
- 所有 SQL 执行均参数化，防注入
- 重要操作需人工审批
- 敏感信息不落盘/日志
- 支持多因子 LLM 授权

---

## 📝 常见问题 FAQ

### 1. UnicodeEncodeError: 'ascii' codec can't encode characters
- 终端需支持 UTF-8，或设置：
  ```bash
  export PYTHONIOENCODING=utf-8
  export PYTHONUTF8=1
  ```

### 2. LLM 初始化失败/无法连接
- 检查 .env 配置、网络、API Key
- 通义千问需 DASHSCOPE_API_KEY，OpenAI 需 OPENAI_API_KEY

### 3. 数据库/知识库索引异常
- 运行 `python data/init_db.py` 初始化 mock 数据
- 知识库需放置于 `data/knowledge/` 目录下

### 4. LangGraph Studio 路由异常
- Studio 环境不会自动加载 .env，需在 llm_client.py 主动 load_dotenv
- 详见 src/core/llm_client.py

---

## 📚 参考文档
- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 官方文档](https://python.langchain.com/)
- [FAISS 官方文档](https://faiss.ai/)
- [通义千问 DashScope](https://help.aliyun.com/zh/dashscope/developer-reference/overview)

---

## 🏆 贡献与致谢
- 本项目参考了 LangChain/LangGraph 官方最佳实践
- 感谢所有开源社区贡献者
