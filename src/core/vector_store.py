# -*- coding: utf-8 -*-
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun


class EnsembleRetriever(BaseRetriever):
    """
    互惠排名融合（RRF）混合检索器。
    当前环境 langchain 1.x 中不再内置 EnsembleRetriever，
    此处基于 langchain_core.retrievers.BaseRetriever 手动实现等价逻辑。
    """
    retrievers: list
    weights: List[float]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        all_results: list[list[Document]] = [r.invoke(query) for r in self.retrievers]

        # 互惠排名融合（RRF）：每个检索器按排名贡献加权分数，最终合并去重排序
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}
        rrf_k = 60  # RRF 常数，业界通用值

        for retriever_docs, weight in zip(all_results, self.weights):
            for rank, doc in enumerate(retriever_docs):
                doc_id = doc.page_content
                rrf_score = weight * (1.0 / (rrf_k + rank + 1))
                scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
                doc_map[doc_id] = doc

        sorted_docs = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        return [doc_map[doc_id] for doc_id in sorted_docs]

ROOT_DIR = Path(__file__).parent.parent.parent.absolute()
load_dotenv(dotenv_path=ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KnowledgeBase:
    """
    基于 FAISS 向量库 + BM25 关键词检索的混合 RAG 知识库，
    通过手写的 EnsembleRetriever（RRF 算法）融合两路召回结果。
    """

    def __init__(self):
        logger.info("🤖 正在启动 LangChain 原生双模检索系统...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            cache_folder=str(ROOT_DIR / "data" / "models")
        )
        self.db_path = ROOT_DIR / "data" / "vector_db"
        self.vector_db = None
        self.ensemble_retriever = None

    def _setup_ensemble(self, chunks):
        """双模检索融合初始化：FAISS（语义）+ BM25（关键词）通过 RRF 算法合并"""
        # 1. 语义检索分支：基于向量相似度召回
        faiss_retriever = self.vector_db.as_retriever(search_kwargs={"k": 2})

        # 2. 关键词检索分支：基于 BM25 词频统计召回
        bm25_retriever = BM25Retriever.from_documents(chunks)
        bm25_retriever.k = 2

        # 3. 互惠排名融合（RRF）：两路结果合并，权重各 50%（可调整）
        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, faiss_retriever],
            weights=[0.5, 0.5]
        )

    def build_index(self):
        knowledge_dir = ROOT_DIR / "data" / "knowledge"
        documents = []

        for file in knowledge_dir.glob("*.md"):
            try:
                loader = TextLoader(str(file), encoding="utf-8")
                documents.extend(loader.load())
            except Exception as e:
                logger.error(f"加载失败: {e}")

        if not documents:
            logger.error("❌ 没找到手册！")
            return False

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_documents(documents)

        self.vector_db = FAISS.from_documents(chunks, self.embeddings)
        self.vector_db.save_local(str(self.db_path))

        self._setup_ensemble(chunks)
        logger.info(f"✅ 官方版混合索引构建完成！")
        return True

    def load_index(self):
        if self.db_path.exists():
            try:
                self.vector_db = FAISS.load_local(
                    str(self.db_path),
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                doc_store = self.vector_db.docstore._dict
                chunks = list(doc_store.values())
                self._setup_ensemble(chunks)
                return True
            except Exception as e:
                logger.error(f"磁盘加载失败: {e}")
        return False

    def query(self, question: str):
        if not self.ensemble_retriever:
            if not self.load_index():
                if not self.build_index():
                    return "❌ 引擎故障"

        # 🌟 学习点：invoke 会自动在底层并行调用 BM25 和 FAISS，然后根据 RRF 算法重新排序
        docs = self.ensemble_retriever.invoke(question)
        return "\n---\n".join([doc.page_content for doc in docs])


if __name__ == "__main__":
    kb = KnowledgeBase()
    kb.build_index()
    print("\n🔍 测试 DPD:")
    print(kb.query("DPD 是什么？"))