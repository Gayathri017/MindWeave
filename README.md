# Mindweave

**Live app:** [mind-weave-zeta.vercel.app](https://mind-weave-zeta.vercel.app)

> This is a personal project built to practice full-stack and AI engineering skills, deployed for a handful of users — not hardened for production scale (e.g. free-tier hosting, no CDN/caching layer, no SMTP domain verified yet for email at scale).
>
> Honest note on AI features: this runs on the free tier of the Gemini API. Image generation, TTS narration, and video understanding (used by the slideshow explainer and YouTube ingestion) have low free-tier rate limits and may fail or throttle under real usage. Everything works reliably on a paid Gemini tier — that's just not turned on here, since this isn't a funded production app.
>
> GraphRAG (Neo4j) is a newer, optional layer on top of the core RAG pipeline, built as a learning exercise in graph-augmented retrieval. It only activates for uploaded research papers/reports and only if Neo4j credentials are configured — everything else works identically without it.

A personal knowledge base that saves whatever you throw at it — a link, a note, a voice memo, a PDF, a receipt, a YouTube video — and lets you ask questions over everything you've saved, in plain English, with real answers grounded in your own material.

Unlike a plain notes app, Mindweave *understands* what you save: it transcribes and summarizes audio, extracts structured data from documents and receipts, watches and understands YouTube videos (not just their page text), builds a live concept graph of how your ideas connect, and answers questions with citations back to the source. It also organizes itself: folders group related items and each get their own persistent, scoped chat, an old note resurfaces once a day so nothing is write-only, and a command palette (`Ctrl+K` / `Cmd+K`) makes the whole thing keyboard-driven.

## Features

**Capture**
- Paste a URL, type a note, or record/upload voice — auto-transcribed in whatever language was spoken.
- Upload a PDF or photo (receipt, research paper, form) — structured fields (line items, totals, key fields, figures) are pulled out automatically.
- Save a YouTube link — Gemini watches the actual video (audio *and* visuals) and produces a real summary, not a scraped page.

**Organize**
- **Folders**, like ChatGPT/Claude Projects: named containers, one per item, each with its own persistent chat scoped only to its contents. Deleting a folder deletes what's in it.
- Three views over the same data: a card list, a sortable table, and a month calendar.
- Filter by type (notes, links, videos, audio, documents).
- A command palette (`Ctrl+K`) for jumping to any item or action without touching the mouse.
- A daily "from your notes" card resurfaces something you saved a while ago.

**Understand & discover**
- Ask questions in a global chat (searches everything) or inside a folder (scoped to just its items) — answers cite the specific saved items they drew from, with clickable chips that jump straight to the source.
- Retrieval reranking: a wide candidate pool is pulled by vector similarity, then the model itself picks out which excerpts are actually relevant before answering — improves precision as your library grows, at no extra API cost.
- Ask by voice instead of typing.
- The assistant can generate an explanatory image inline when a diagram would help more than text.
- **Explain as a slideshow**: turn any saved item into a short narrated explainer — a script broken into scenes, each with a generated image and generated narration audio.
- An auto-built concept graph shows which ideas in your notes keep coming back together.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python), async throughout |
| Database | Postgres + pgvector, hosted on Supabase |
| Auth | Supabase Auth (magic link), enforced via real Postgres Row-Level Security |
| AI | Google Gemini — chat (`gemini-3.8-flash`), embeddings (`gemini-embedding-001`), transcription, image generation, TTS, video understanding — one provider, one client module |
| Retrieval | Hybrid RAG: pgvector similarity search over chunked + embedded items, then an LLM reranking pass over the candidate pool, plus a GraphRAG step (see below) that adds related facts before answering — with citations back to source items |
| GraphRAG | Neo4j (AuraDB) — for research papers/reports, Gemini also extracts typed (subject, relation, object) triples (e.g. "GraphRAG outperforms vector-only RAG"), written to a graph. At answer time, facts tied to the matched items — plus a one-hop expansion to related items elsewhere in the graph — are added to the prompt alongside the vector-search excerpts. Optional: fully disabled with no config changes if Neo4j isn't set up |
| Web grounding | Tavily API — real, cited web search results when a question isn't covered by saved items |
| Frontend | React + Vite |
| Concept graph (visualization) | A separate, simpler graph — co-occurring concepts stored as plain Postgres tables, rendered with react-force-graph-2d. This one is visualization only, independent of the Neo4j GraphRAG pipeline above |
| Backend hosting | Render |
| Frontend hosting | Vercel |

## Project structure

```
backend/    FastAPI API, Gemini integration, Postgres access, tests
frontend/   React app (Vite)
```

Each has its own `README.md` with detailed setup instructions:

- [`backend/README.md`](backend/README.md) — environment setup, running the API, running tests (including the integration test database)
- [`frontend/README.md`](frontend/README.md) — running the dev server

## Quick start

```bash
# Backend
cd backend
uv venv && uv pip install -r requirements-dev.txt
# fill in .env (see backend/README.md for what's needed)
uv run python run.py        # Windows
uvicorn app.main:app --reload  # Mac/Linux

# Frontend, in a second terminal
cd frontend
npm install
npm run dev
```

## Security model worth knowing about

This backend connects to Postgres directly (not through Supabase's PostgREST layer), and deliberately keeps Row-Level Security switched on anyway: every request verifies the caller's JWT, then sets the same session variables PostgREST would have set before running any query. That means a bug in application code that forgot to filter by user ID still cannot leak another user's data — the database itself refuses. See `backend/app/database.py` for the details.

## A note on how this was built

Built using Claude as a development tool.

## License

MIT — see [LICENSE](LICENSE).
