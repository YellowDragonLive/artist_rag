# -*- coding: utf-8 -*-
"""
RAG 引擎 - 知识库构建入口
一键从数据源构建完整的向量知识库
"""
import logging
import sys
import time

from .chunker import load_all_artist_data, chunk_artist_data
from .vector_store import build_index, get_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_knowledge_base(force_rebuild: bool = True) -> dict:
    """
    一键构建画师风格 RAG 知识库

    流程:
    1. 加载所有画师数据（noobai_data.json + collected profiles）
    2. 多维度切分文本块
    3. 写入 ChromaDB 向量索引

    Args:
        force_rebuild: 是否强制重建索引

    Returns:
        构建统计信息
    """
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("  画师风格 RAG 知识库构建器")
    logger.info("=" * 60)

    # Step 1: 加载数据
    logger.info("\n[Step 1] 加载画师数据...")
    artists = load_all_artist_data()
    logger.info(f"  加载了 {len(artists)} 位有风格数据的画师")

    # Step 2: 文本分块
    logger.info("\n[Step 2] 文本分块...")
    chunks = chunk_artist_data(artists)
    logger.info(f"  生成了 {len(chunks)} 个文本块")

    # 统计 chunk 类型分布
    type_counts: dict[str, int] = {}
    for c in chunks:
        type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1
    for ctype, count in type_counts.items():
        logger.info(f"    - {ctype}: {count} 个")

    # Step 3: 构建向量索引
    logger.info("\n[Step 3] 构建 ChromaDB 向量索引...")
    total_records = build_index(chunks, force_rebuild=force_rebuild)

    # 统计
    elapsed = time.time() - start_time
    stats = get_stats()
    stats["artists_count"] = len(artists)
    stats["chunks_count"] = len(chunks)
    stats["build_time_seconds"] = round(elapsed, 2)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  构建完成!")
    logger.info(f"  画师数: {len(artists)}")
    logger.info(f"  文本块数: {len(chunks)}")
    logger.info(f"  向量记录数: {total_records}")
    logger.info(f"  耗时: {elapsed:.2f} 秒")
    logger.info(f"{'=' * 60}")

    return stats


def main():
    """命令行入口"""
    force = "--force" in sys.argv or "-f" in sys.argv
    build_knowledge_base(force_rebuild=force)


if __name__ == "__main__":
    main()
