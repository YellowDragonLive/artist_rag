# -*- coding: utf-8 -*-
"""
RAG 引擎 - 轻量级向量存储与检索
使用 scikit-learn TF-IDF + Cosine Similarity 实现语义检索
无需 PyTorch / ONNX / ChromaDB 等重依赖
"""
import json
import logging
import os
import pickle
from typing import Optional

from .config import RAG_DB_DIR, DEFAULT_TOP_K, NOOBAI_DATA_FILE, COLLECTED_PROFILES
from .chunker import ArtistChunk

logger = logging.getLogger(__name__)

# 全局缓存
_vectorizer = None
_tfidf_matrix = None
_chunk_store: list[dict] = []
_INDEX_FILE = os.path.join(RAG_DB_DIR, "tfidf_index.pkl")


def _load_index() -> bool:
    """从磁盘加载持久化的 TF-IDF 索引"""
    global _vectorizer, _tfidf_matrix, _chunk_store

    if _vectorizer is not None:
        return True

    if not os.path.exists(_INDEX_FILE):
        return False

    try:
        with open(_INDEX_FILE, "rb") as f:
            data = pickle.load(f)
        _vectorizer = data["vectorizer"]
        _tfidf_matrix = data["matrix"]
        _chunk_store = data["chunks"]
        logger.info(f"已从磁盘加载索引: {len(_chunk_store)} 条记录")
        return True
    except (EOFError, pickle.UnpicklingError, KeyError) as e:
        logger.warning(f"索引加载失败: {e}")
        return False


def _save_index() -> None:
    """将 TF-IDF 索引持久化到磁盘"""
    os.makedirs(RAG_DB_DIR, exist_ok=True)
    with open(_INDEX_FILE, "wb") as f:
        pickle.dump(
            {
                "vectorizer": _vectorizer,
                "matrix": _tfidf_matrix,
                "chunks": _chunk_store,
            },
            f,
        )
    logger.info(f"索引已保存至: {_INDEX_FILE}")


def build_index(chunks: list[ArtistChunk], force_rebuild: bool = False) -> int:
    """
    构建 TF-IDF 向量索引

    Args:
        chunks: 文本块列表
        force_rebuild: 是否强制重建

    Returns:
        索引中的记录数
    """
    global _vectorizer, _tfidf_matrix, _chunk_store

    if not force_rebuild and _load_index():
        logger.info("使用已有索引")
        return len(_chunk_store)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError as exc:
        raise ImportError(
            "请先安装 scikit-learn: pip install scikit-learn"
        ) from exc

    # 准备文档
    documents = []
    _chunk_store = []

    for chunk in chunks:
        documents.append(chunk.content)
        _chunk_store.append(
            {
                "chunk_id": chunk.chunk_id,
                "artist_name": chunk.artist_name,
                "artist_index": chunk.artist_index,
                "content": chunk.content,
                "chunk_type": chunk.chunk_type,
                "metadata": {
                    **chunk.metadata,
                    "artist_name": chunk.artist_name,
                    "artist_index": chunk.artist_index,
                    "chunk_type": chunk.chunk_type,
                },
            }
        )

    # 构建 TF-IDF 向量化器
    # 使用 char_wb analyzer 支持中英文混合检索
    _vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),  # 2-4字元的n-gram
        max_features=20000,
        sublinear_tf=True,
        min_df=1,
    )

    _tfidf_matrix = _vectorizer.fit_transform(documents)

    # 持久化
    _save_index()

    logger.info(f"TF-IDF 索引构建完成: {len(documents)} 条文档, {_tfidf_matrix.shape[1]} 个特征")
    return len(documents)


def search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    chunk_type: Optional[str] = None,
    core_only: bool = False,
) -> list[dict]:
    """
    在知识库中检索最相关的画师风格

    使用 TF-IDF + Cosine Similarity 进行检索
    支持中英文混合查询

    Args:
        query: 查询文本
        top_k: 返回结果数
        chunk_type: 限定搜索的 chunk 类型
        core_only: 是否仅搜索核心画师

    Returns:
        检索结果列表
    """
    if not _load_index():
        logger.warning("索引未构建，请先运行 builder")
        return []

    try:
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as exc:
        raise ImportError("请先安装 scikit-learn") from exc

    # 将查询转换为 TF-IDF 向量
    query_vec = _vectorizer.transform([query])

    # 计算余弦相似度
    similarities = cosine_similarity(query_vec, _tfidf_matrix).flatten()

    # 过滤和排序
    scored_results = []
    for idx, sim_score in enumerate(similarities):
        if sim_score <= 0:
            continue

        chunk = _chunk_store[idx]

        # 类型过滤
        if chunk_type and chunk.get("chunk_type") != chunk_type:
            continue

        # 核心画师过滤
        if core_only:
            is_core = chunk.get("metadata", {}).get("is_core", "False")
            if is_core != "True" and is_core is not True:
                continue

        scored_results.append(
            {
                "chunk_id": chunk["chunk_id"],
                "artist_name": chunk["artist_name"],
                "artist_index": chunk["artist_index"],
                "content": chunk["content"],
                "similarity": round(float(sim_score), 4),
                "metadata": chunk.get("metadata", {}),
            }
        )

    # 按相似度降序排列
    scored_results.sort(key=lambda x: x["similarity"], reverse=True)

    # 去重（同一画师只保留最高分的结果）
    seen_artists = set()
    deduped = []
    for r in scored_results:
        if r["artist_name"] not in seen_artists:
            seen_artists.add(r["artist_name"])
            deduped.append(r)
        if len(deduped) >= top_k:
            break

    return deduped


def get_stats() -> dict:
    """获取知识库统计信息"""
    _load_index()
    return {
        "total_chunks": len(_chunk_store),
        "index_file": _INDEX_FILE,
        "index_exists": os.path.exists(_INDEX_FILE),
        "engine": "TF-IDF (scikit-learn)",
    }
