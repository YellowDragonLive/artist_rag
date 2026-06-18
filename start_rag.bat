@echo off
title NoobAI Artist Style RAG Knowledge Base
color 0b

echo ============================================================
echo     NoobAI Artist Style RAG - Knowledge Base Server
echo ============================================================
echo.

echo [Step 1] Checking Python dependencies (scikit-learn)...
pip install -q scikit-learn fastapi uvicorn 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may not have installed correctly.
    echo [WARNING] Please run: pip install scikit-learn fastapi uvicorn
)

echo.
echo [Step 2] Checking/Creating knowledge base index...
cd /d "%~dp0"
if not exist "rag_knowledge_base\chroma_db\tfidf_index.pkl" (
    echo [INFO] Index not found, building from scratch...
    python -X utf8 -m rag_engine.builder --force
) else (
    echo [INFO] Index exists, skipping build. Use --force to rebuild.
)

echo.
echo [Step 3] Starting RAG API Server on port 3001...
echo [INFO] API: POST /api/rag/search  GET /api/rag/search?q=...  GET /api/rag/stats
echo [INFO] Press Ctrl+C to stop.
echo ============================================================
python -X utf8 -m rag_engine.server

pause
