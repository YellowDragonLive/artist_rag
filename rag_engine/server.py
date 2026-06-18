# -*- coding: utf-8 -*-
"""
RAG 引擎 - FastAPI 查询服务
提供 RESTful API 用于前端和 LLM 查询画师风格知识库
"""
import logging

from .config import RAG_SERVER_HOST, RAG_SERVER_PORT
from .vector_store import search, get_stats
from .builder import build_knowledge_base

logger = logging.getLogger(__name__)

# 延迟导入 FastAPI，仅在启动服务时需要
_app = None


def create_app():
    """创建 FastAPI 应用"""
    global _app
    if _app is not None:
        return _app

    try:
        from fastapi import FastAPI, Query
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as exc:
        raise ImportError(
            "请先安装 fastapi 和 uvicorn: pip install fastapi uvicorn"
        ) from exc

    class SearchRequest(BaseModel):
        """搜索请求体"""
        query: str
        top_k: int = 5
        chunk_type: str | None = None
        core_only: bool = False

    class SearchResult(BaseModel):
        """搜索结果项"""
        chunk_id: str
        artist_name: str
        artist_index: int
        content: str
        similarity: float
        metadata: dict

    class SearchResponse(BaseModel):
        """搜索响应"""
        query: str
        results: list[SearchResult]
        total: int

    _app = FastAPI(
        title="NoobAI 画师风格 RAG 知识库",
        description="为伟大的人工智能驾驭者 Eric.hls 打造的画师风格语义检索 API",
        version="1.0.0",
    )

    # CORS 配置 - 允许前端跨域访问
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @_app.get("/")
    async def root():
        """服务状态检查"""
        stats = get_stats()
        return {
            "service": "NoobAI Artist Style RAG",
            "status": "running",
            "stats": stats,
        }

    @_app.post("/api/rag/search", response_model=SearchResponse)
    async def rag_search(request: SearchRequest):
        """
        语义搜索画师风格

        支持中英文查询，返回最相关的画师风格信息。
        示例查询:
        - "厚涂暗色调逆光"
        - "萌系水彩治愈"
        - "semi-realistic korean glamour"
        """
        results = search(
            query=request.query,
            top_k=request.top_k,
            chunk_type=request.chunk_type,
            core_only=request.core_only,
        )

        return SearchResponse(
            query=request.query,
            results=[SearchResult(**r) for r in results],
            total=len(results),
        )

    @_app.get("/api/rag/search")
    async def rag_search_get(
        q: str = Query(..., description="查询文本"),
        top_k: int = Query(5, description="返回结果数"),
        chunk_type: str | None = Query(None, description="chunk类型过滤"),
        core_only: bool = Query(False, description="仅搜索核心画师"),
    ):
        """GET 方式的语义搜索（方便浏览器测试）"""
        results = search(
            query=q,
            top_k=top_k,
            chunk_type=chunk_type,
            core_only=core_only,
        )

        return {
            "query": q,
            "results": results,
            "total": len(results),
        }

    @_app.get("/api/rag/stats")
    async def rag_stats():
        """获取知识库统计信息"""
        return get_stats()

    @_app.post("/api/rag/rebuild")
    async def rag_rebuild():
        """重建知识库索引"""
        stats = build_knowledge_base(force_rebuild=True)
        return {"message": "知识库重建完成", "stats": stats}

    return _app


def start_server():
    """启动 RAG 服务"""
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "请先安装 uvicorn: pip install uvicorn"
        ) from exc

    app = create_app()

    logger.info(f"RAG 服务启动于 http://{RAG_SERVER_HOST}:{RAG_SERVER_PORT}")
    logger.info(f"API 文档: http://localhost:{RAG_SERVER_PORT}/docs")

    uvicorn.run(
        app,
        host=RAG_SERVER_HOST,
        port=RAG_SERVER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_server()
