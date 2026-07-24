#!/usr/bin/env python3
"""Lance l'interface web de l'agent de veille v3."""
import os
import sys
import uvicorn

# Magasin de certificats système (antivirus / proxy TLS) — voir main.py
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))

    print("🚀 Agent de Veille Tech v3 — Interface Web")
    print("📍 URL        : http://localhost:8000")
    print("📍 API docs   : http://localhost:8000/docs")
    print("📍 API status : http://localhost:8000/api/status")
    print("")
    print("Variable d'environnement requise (dans .env) :")
    print("  OPENAI_API_KEY=sk-...   ou   ANTHROPIC_API_KEY=sk-ant-...")
    print("  GITHUB_TOKEN=ghp_...  (optionnel — 5000 req/h au lieu de 60)")

    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
