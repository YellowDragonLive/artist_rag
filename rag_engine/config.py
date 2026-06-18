# -*- coding: utf-8 -*-
"""RAG 引擎配置常量"""

import os

# 项目根目录
BASE_DIR = r"x:\game\noobaiStyleCollection_v12\艺术家智能选择"

# 数据文件路径
NOOBAI_DATA_FILE = os.path.join(BASE_DIR, "noobai_data.json")
KNOWLEDGE_BASE_MD = os.path.join(BASE_DIR, "NOOBAI_ARTISTS_KNOWLEDGE_BASE.md")
COLLECTED_PROFILES = os.path.join(BASE_DIR, "artist_profiles", "artist_styles_collected.json")

# RAG 知识库路径
RAG_BASE_DIR = os.path.join(BASE_DIR, "rag_knowledge_base")
RAG_DOCS_DIR = os.path.join(RAG_BASE_DIR, "documents")
RAG_DB_DIR = os.path.join(RAG_BASE_DIR, "chroma_db")

# ChromaDB 配置
CHROMA_COLLECTION_NAME = "noobai_artist_styles"

# 嵌入模型 (ChromaDB DefaultEmbeddingFunction = all-MiniLM-L6-v2 ONNX, 384维)
# 此常量仅作记录, 实际由 ChromaDB 默认嵌入函数提供
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2 (ONNX, via ChromaDB DefaultEmbeddingFunction)"

# 检索配置
DEFAULT_TOP_K = 5  # 默认返回前 K 个最相关结果

# FastAPI 配置
RAG_SERVER_HOST = "0.0.0.0"
RAG_SERVER_PORT = 3001
