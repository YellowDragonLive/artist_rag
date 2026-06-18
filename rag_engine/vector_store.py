# -*- coding: utf-8 -*-
"""
RAG 引擎 - ChromaDB 向量存储与检索 (方案 A)

使用 ChromaDB + 默认 ONNX 嵌入函数 (all-MiniLM-L6-v2) 实现语义检索。
依赖: chromadb, onnxruntime (conda-forge CPU 版), scikit-learn (ChromaDB 间接依赖)

环境要求: C:\\Users\\13410\\rag_env (用户目录 conda env, 隔离 DLL 冲突)
"""
import logging
import os
from typing import Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from .config import (
    RAG_DB_DIR,
    CHROMA_COLLECTION_NAME,
    DEFAULT_TOP_K,
)
from .chunker import ArtistChunk

logger = logging.getLogger(__name__)

# 全局客户端与集合缓存
_client: Optional[chromadb.api.ClientAPI] = None
_collection: Optional[chromadb.api.Collection] = None
_embedding_function = None


def _get_client() -> chromadb.api.ClientAPI:
    """获取(惰性初始化) ChromaDB PersistentClient"""
    global _client
    if _client is None:
        os.makedirs(RAG_DB_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=RAG_DB_DIR,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        logger.info(f"ChromaDB PersistentClient 已初始化: {RAG_DB_DIR}")
    return _client


def _get_embedding_function():
    """获取(惰性初始化) 默认 ONNX 嵌入函数"""
    global _embedding_function
    if _embedding_function is None:
        # ChromaDB 默认嵌入函数: all-MiniLM-L6-v2 (ONNX, 384维)
        # 首次调用会下载模型至 ~/.cache/chroma/onnx_models/
        _embedding_function = embedding_functions.DefaultEmbeddingFunction()
        logger.info("DefaultEmbeddingFunction (all-MiniLM-L6-v2 ONNX) 已初始化")
    return _embedding_function


def _get_collection() -> chromadb.api.Collection:
    """获取(惰性初始化) 目标 Collection"""
    global _collection
    if _collection is None:
        client = _get_client()
        ef = _get_embedding_function()
        _collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Collection 已就绪: {CHROMA_COLLECTION_NAME}")
    return _collection


def build_index(chunks: list[ArtistChunk], force_rebuild: bool = False) -> int:
    """
    构建 ChromaDB 向量索引

    Args:
        chunks: 文本块列表
        force_rebuild: 是否强制重建(删除已有 collection 后重建)

    Returns:
        索引中的记录数
    """
    client = _get_client()
    ef = _get_embedding_function()

    if force_rebuild:
        # 删除已有 collection 后重建
        try:
            client.delete_collection(name=CHROMA_COLLECTION_NAME)
            logger.info(f"已删除旧 collection: {CHROMA_COLLECTION_NAME}")
        except Exception:
            # collection 不存在时静默忽略
            pass
        global _collection
        _collection = None

    collection = _get_collection()

    # 批量插入 (ChromaDB upsert, 幂等)
    batch_size = 100
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        ids = [c.chunk_id for c in batch]
        documents = [c.content for c in batch]
        metadatas = [
            {
                **c.metadata,
                "artist_name": c.artist_name,
                "artist_index": c.artist_index,
                "chunk_type": c.chunk_type,
                # ChromaDB metadata 值必须是基础类型, is_core 转 str
                "is_core": str(c.metadata.get("is_core", False)),
            }
            for c in batch
        ]
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        total += len(batch)

    logger.info(
        f"ChromaDB 索引构建完成: {total} 条文档 -> collection '{CHROMA_COLLECTION_NAME}'"
    )
    return total


def search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    chunk_type: Optional[str] = None,
    core_only: bool = False,
) -> list[dict]:
    """
    在知识库中检索最相关的画师风格

    使用 ChromaDB + ONNX 嵌入进行语义检索

    Args:
        query: 查询文本
        top_k: 返回结果数
        chunk_type: 限定搜索的 chunk 类型
        core_only: 是否仅搜索核心画师

    Returns:
        检索结果列表
    """
    try:
        collection = _get_collection()
    except Exception as e:
        logger.warning(f"Collection 未就绪: {e}")
        return []

    # 构建 where 过滤条件
    where = {}
    if chunk_type:
        where["chunk_type"] = chunk_type
    if core_only:
        where["is_core"] = "True"

    # ChromaDB query 需要 n_results >= top_k (因为可能同画师多 chunk)
    fetch_n = top_k * 4 if top_k > 0 else 20

    try:
        results = collection.query(
            query_texts=[query],
            n_results=fetch_n,
            where=where if where else None,
        )
    except Exception as e:
        logger.error(f"ChromaDB 查询失败: {e}")
        return []

    # 解析结果 (ChromaDB 返回 dict of lists)
    ids_batch = results.get("ids", [[]])
    docs_batch = results.get("documents", [[]])
    metas_batch = results.get("metadatas", [[]])
    dists_batch = results.get("distances", [[]])

    if not ids_batch or not ids_batch[0]:
        return []

    scored = []
    for idx, cid in enumerate(ids_batch[0]):
        distance = dists_batch[0][idx] if idx < len(dists_batch[0]) else 1.0
        # cosine distance -> similarity
        similarity = round(1.0 - float(distance), 4)
        meta = metas_batch[0][idx] if idx < len(metas_batch[0]) else {}
        scored.append(
            {
                "chunk_id": cid,
                "artist_name": meta.get("artist_name", ""),
                "artist_index": meta.get("artist_index", -1),
                "content": docs_batch[0][idx] if idx < len(docs_batch[0]) else "",
                "similarity": similarity,
                "metadata": meta,
            }
        )

    # 按相似度降序
    scored.sort(key=lambda x: x["similarity"], reverse=True)

    # 去重 (同一画师只保留最高分)
    seen_artists = set()
    deduped = []
    for r in scored:
        if r["artist_name"] not in seen_artists:
            seen_artists.add(r["artist_name"])
            deduped.append(r)
        if len(deduped) >= top_k:
            break

    return deduped


def get_stats() -> dict:
    """获取知识库统计信息"""
    index_exists = os.path.exists(os.path.join(RAG_DB_DIR, "chroma.sqlite3"))
    total_chunks = 0
    try:
        collection = _get_collection()
        total_chunks = collection.count()
    except Exception:
        pass

    return {
        "total_chunks": total_chunks,
        "index_file": os.path.join(RAG_DB_DIR, "chroma.sqlite3"),
        "index_exists": index_exists,
        "engine": "ChromaDB + all-MiniLM-L6-v2 ONNX",
        "collection_name": CHROMA_COLLECTION_NAME,
    }
