@echo off
title NoobAI Artist Style RAG Knowledge Base
color 0b

echo ============================================================
echo     NoobAI Artist Style RAG - Knowledge Base Server
echo ============================================================
echo.

set "PY=C:\Users\13410\rag_env\python.exe"
if not exist "%PY%" (
    echo [ERROR] RAG env python not found: %PY%
    echo [ERROR] Please create env: conda create -p C:\Users\13410\rag_env python=3.10
    pause
    exit /b 1
)

echo [Step 1] Checking knowledge base index...
cd /d "%~dp0"
if not exist "rag_knowledge_base\chroma_db\chroma.sqlite3" (
    echo [INFO] Index not found, building from scratch...
    "%PY%" -X utf8 -m rag_engine.builder --force
) else (
    echo [INFO] Index exists, skipping build. Use --force to rebuild.
)

echo.
echo [Step 2] Starting RAG API Server on port 3001...
echo [INFO] API: POST /api/rag/search  GET /api/rag/search?q=...  GET /api/rag/stats
echo [INFO] Press Ctrl+C to stop.
echo ============================================================
"%PY%" -X utf8 -m rag_engine.server

pause
