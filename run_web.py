#!/usr/bin/env python3
"""Lance l'interface web de l'agent de veille v2."""
import os
import sys
import uvicorn

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))

    print("🚀 Agent de Veille Tech v2 — Interface Web")
    print("📍 URL        : http://localhost:8000")
    print("📍 API docs   : http://localhost:8000/docs")
    print("📍 API status : http://localhost:8000/api/status")
    print("")
    print("Variables d'environnement requises selon le provider LLM :")
    print("  Anthropic : export ANTHROPIC_API_KEY=sk-ant-...")
    print("  OpenAI    : export OPENAI_API_KEY=sk-...")
    print("  Ollama    : (aucune — doit tourner sur localhost:11434)")

    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
