# Mindweave -- backend (Phase 3 + 4: ingestion, RAG, and the concept graph)

This is the backend service for Mindweave. So far it implements: saving an
item (a pasted URL or note), chunking + embedding it, answering questions
over a user's own saved knowledge with retrieval-augmented generation
(RAG), and automatically extracting concepts from each item to build a
graph of how your ideas connect -- no manual linking required.

**Not yet implemented** (later phases): the frontend, and production
deployment config.

## Stack

- FastAPI (Python 3.11+)
- Postgres + pgvector, hosted on Supabase
- Supabase Auth (magic-link) for identity -- this backend verifies tokens,
  it doesn't issue them
- Gemini API (`gemini-embedding-001` for embeddings, `gemini-3.8-flash` for chat)

## One-time setup

1. Create a free Supabase project.
2. In the Supabase SQL editor, run `db/schema.sql` to create the tables,
   indexes, and Row Level Security policies.
3. In Supabase project settings, grab:
   - your Postgres connection string (**Session pooler**, not the direct
     connection -- copy the URI and change `postgresql://` to
     `postgresql+asyncpg://`)
   - your project URL and your anon/publishable key (both under
     Settings -> API Keys) -- used to verify session tokens against
     Supabase's public JWKS endpoint
4. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
5. Copy `.env.example` to `.env` and fill in the values above.

## Run locally

**Mac/Linux:**
```bash
uv venv
uv pip install -r requirements.txt
uv run uvicorn app.main:app --reload
```

**Windows:**
```bash
uv venv
uv pip install -r requirements.txt
uv run python run.py
```

Windows uses `run.py` instead of `uvicorn ... --reload` directly, to work
around a known Windows/asyncio DNS resolution quirk -- see the comment at
the top of `run.py` for why. It also means no auto-reload on Windows for
now: stop (Ctrl+C) and re-run after code changes.

(No `uv`? Swap `uv pip install` for `pip install` after activating a venv
the usual way -- everything else is the same.)

Visit `http://localhost:8000/health` -- you should see `{"status": "ok"}`.

## Run the tests

```bash
pytest
```

## A security detail worth understanding

Session tokens are verified against Supabase's public JWKS endpoint
(`/auth/v1/.well-known/jwks.json`), not a shared secret -- Supabase signs tokens with a
private key that never leaves their servers, and this backend only ever
holds the corresponding *public* key, fetched and cached automatically.
That means a leaked `.env` file can't be used to forge a valid session,
which a leaked shared secret could. See `app/auth.py` for the details.

This backend also connects to Postgres directly rather than through Supabase's
PostgREST layer, which means the usual "Row Level Security just works"
story needs one extra step: every request explicitly switches into
Postgres's `authenticated` role and sets the same session variable
PostgREST would have set, using the user id from their *verified* JWT --
never from anything the client claims. See `app/database.py` for exactly
how and why. The result is that even a bug in application code that
forgot to filter a query by user id still could not leak another user's
data -- the database itself refuses.

## API

- `POST /api/items` -- save a URL or note
  `{"source_type": "url" | "text", "content": "..."}`
- `POST /api/chat` -- ask a question over your saved items
  `{"question": "..."}`
- `GET /api/graph` -- your full concept graph so far: `{"nodes": [...], "edges": [...]}`,
  where each node is a concept and each edge's `weight` grows every time
  that pair of concepts co-occurs in another saved item

All three require `Authorization: Bearer <supabase-access-token>`.

## What's next (Phase 5)

The frontend: sign-in, the save/chat UI, and rendering `/api/graph` as an
actual interactive graph the user can explore.
