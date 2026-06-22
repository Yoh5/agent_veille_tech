# 🤖 Agent de Veille Tech v2

Pipeline Python autonome : scan multi-sources → déduplication → scoring → résumé LLM → brief Markdown quotidien.

## 🆕 Nouveautés v2

| Fonctionnalité | v1 | v2 |
|---|---|---|
| LLM supportés | OpenAI seulement | **Anthropic, OpenAI, Ollama (local)** |
| Sources RSS | Ars Technica hardcodé | **N flux RSS configurables** |
| Déduplication | ❌ | **✅ Persistante (fenêtre configurable)** |
| Score freshness | ❌ | **✅ Bonus articles < 6h** |
| Détection tendances | ❌ | **✅ Mots-clés les plus actifs** |
| Signal LLM | ❌ | **✅ émergent / confirmé / alerte / neutre** |
| Export PDF | wkhtmltopdf (lourd) | **⬇ .md natif (sans dépendance)** |
| Switch LLM UI | ❌ | **✅ Depuis l'interface web** |
| Endpoint API | ❌ | **✅ /api/status pour n8n/webhooks** |
| Sources HN/Reddit | Fix | Enrichies (points, commentaires) |

## Architecture

```
config.yaml
    │
    ▼
fetcher.py ──► hackernews.py
           ──► reddit.py
           ──► rss_feeds.py  (N flux RSS configurables)
    │
    ▼
filter.py ──► déduplication (seen_articles.json)
          ──► scoring (mots-clés + freshness + poids source)
          ──► détection tendances
    │
    ▼
summarize.py ──► Anthropic | OpenAI | Ollama
    │
    ▼
brief_generator.py ──► output/briefs/brief_veille_YYYY-MM-DD.md
```

## Installation

```bash
# 1. Cloner / décompresser
cd veille-agent-v2

# 2. Environnement virtuel
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 3. Dépendances
pip install -r requirements.txt

# 4. Clé API selon le provider choisi
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic (défaut)
# ou
export OPENAI_API_KEY="sk-..."          # OpenAI
# ou : démarrer Ollama localement (http://localhost:11434)
```

## Utilisation

```bash
# CLI
python main.py

# Interface web
python run_web.py
# → http://localhost:8000
```

## Configuration LLM

Éditez `config.yaml` :

```yaml
llm:
  provider: anthropic          # openai | anthropic | ollama
  model: claude-sonnet-4-6     # ou gpt-4o-mini ou llama3.2
  temperature: 0.3
  max_tokens: 500
```

Ou changez le provider directement depuis l'interface web (section LLM Provider).

## Ajouter des sources RSS

Dans votre profil `config.yaml` :

```yaml
rss_feeds:
  enabled: true
  feeds:
    - name: "Mon blog favori"
      url: "https://monblog.com/feed.xml"
      weight: 1.2
    - name: "Hugging Face"
      url: "https://huggingface.co/blog/feed.xml"
      weight: 1.4
  max_entries_per_feed: 8
```

## Planification (cron)

```bash
# Tous les jours à 7h30
30 7 * * * cd /chemin/veille-agent-v2 && python main.py >> /var/log/veille.log 2>&1
```

## Intégration n8n

- Endpoint webhook : `POST http://localhost:8000/run`
- Status JSON : `GET http://localhost:8000/api/status`
- Le brief `.md` généré peut être lu et envoyé sur Slack/Email via n8n

## Stack

- Python 3.10+
- `requests` + `feedparser` (fetch)
- `anthropic` / `openai` (résumé LLM)
- `pyyaml` (config)
- `fastapi` + `uvicorn` (interface web)
