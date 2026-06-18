# -*- coding: utf-8 -*-
"""
RAG 引擎 - 文本分块器
将画师风格文档按语义维度切分为适合嵌入的文本块
"""
import json
import os
import logging
from typing import Optional

from .config import NOOBAI_DATA_FILE, COLLECTED_PROFILES, RAG_DOCS_DIR

logger = logging.getLogger(__name__)


class ArtistChunk:
    """画师文本块数据结构"""

    def __init__(
        self,
        chunk_id: str,
        artist_name: str,
        artist_index: int,
        content: str,
        chunk_type: str = "full",
        metadata: Optional[dict] = None,
    ):
        self.chunk_id = chunk_id
        self.artist_name = artist_name
        self.artist_index = artist_index
        self.content = content
        self.chunk_type = chunk_type
        self.metadata = metadata or {}


def load_all_artist_data() -> list[dict]:
    """
    从 noobai_data.json 和 collected profiles 加载完整画师数据

    Returns:
        包含所有有风格数据画师的列表
    """
    # 加载 noobai_data.json
    with open(NOOBAI_DATA_FILE, "r", encoding="utf-8") as f:
        noobai_data = json.load(f)

    # 加载采集的详细数据
    collected_map = {}
    if os.path.exists(COLLECTED_PROFILES):
        with open(COLLECTED_PROFILES, "r", encoding="utf-8") as f:
            collected_data = json.load(f)
        for artist in collected_data.get("artists", []):
            collected_map[artist["name"]] = artist

    # 合并数据
    result = []
    for idx, artist in enumerate(noobai_data.get("artists", []), 1):
        name = artist.get("name", "")
        styles = artist.get("styles", [])
        if len(styles) == 0:
            continue

        entry = {
            "index": idx,
            "name": name,
            "styles": styles,
        }

        # 合并采集的详细数据
        if name in collected_map:
            coll = collected_map[name]
            entry.update(
                {
                    "name_cn": coll.get("name_cn", ""),
                    "genre": coll.get("genre", ""),
                    "genre_en": coll.get("genre_en", ""),
                    "description": coll.get("description", ""),
                    "weight": coll.get("weight", ""),
                    "is_core": coll.get("is_core", False),
                }
            )

        result.append(entry)

    return result


def chunk_artist_data(artists: list[dict]) -> list[ArtistChunk]:
    """
    将画师数据切分为多维度文本块

    每位画师生成以下类型的 chunk:
    1. full - 完整风格描述（用于综合检索）
    2. styles_cn - 纯中文风格标签（用于中文关键词检索）
    3. styles_en - 纯英文风格标签（用于英文/Prompt检索）
    4. description - 详细描述段落（用于语义检索）

    Args:
        artists: 画师数据列表

    Returns:
        文本块列表
    """
    chunks: list[ArtistChunk] = []

    for artist in artists:
        name = artist["name"]
        idx = artist["index"]
        styles = artist.get("styles", [])

        # 分离中英文标签
        cn_styles = [s for s in styles if any("\u4e00" <= c <= "\u9fff" for c in s)]
        en_styles = [
            s for s in styles if not any("\u4e00" <= c <= "\u9fff" for c in s)
        ]

        # Chunk 1: 完整风格描述
        full_parts = [f"画师: {name} (#{idx})"]
        if artist.get("name_cn"):
            full_parts.append(f"中文名: {artist['name_cn']}")
        if artist.get("genre"):
            full_parts.append(f"流派: {artist['genre']}")
        if artist.get("description"):
            full_parts.append(f"风格描述: {artist['description']}")
        full_parts.append(f"风格标签: {', '.join(styles)}")
        if artist.get("weight"):
            full_parts.append(f"推荐权重: {artist['weight']}")

        chunks.append(
            ArtistChunk(
                chunk_id=f"artist_{idx}_full",
                artist_name=name,
                artist_index=idx,
                content="\n".join(full_parts),
                chunk_type="full",
                metadata={
                    "genre": artist.get("genre", ""),
                    "is_core": artist.get("is_core", False),
                    "weight": artist.get("weight", ""),
                },
            )
        )

        # Chunk 2: 中文标签聚合
        if cn_styles:
            cn_content = f"画师 {name} (#{idx}) 的中文风格: {', '.join(cn_styles)}"
            if artist.get("genre"):
                cn_content += f"\n流派: {artist['genre']}"
            chunks.append(
                ArtistChunk(
                    chunk_id=f"artist_{idx}_cn",
                    artist_name=name,
                    artist_index=idx,
                    content=cn_content,
                    chunk_type="styles_cn",
                )
            )

        # Chunk 3: 英文标签聚合
        if en_styles:
            en_content = f"Artist {name} (#{idx}) English style tags: {', '.join(en_styles)}"
            if artist.get("genre_en"):
                en_content += f"\nGenre: {artist['genre_en']}"
            chunks.append(
                ArtistChunk(
                    chunk_id=f"artist_{idx}_en",
                    artist_name=name,
                    artist_index=idx,
                    content=en_content,
                    chunk_type="styles_en",
                )
            )

        # Chunk 4: 详细描述（如有）
        if artist.get("description"):
            chunks.append(
                ArtistChunk(
                    chunk_id=f"artist_{idx}_desc",
                    artist_name=name,
                    artist_index=idx,
                    content=artist["description"],
                    chunk_type="description",
                )
            )

    logger.info(f"共切分 {len(chunks)} 个文本块，来自 {len(artists)} 位画师")
    return chunks
