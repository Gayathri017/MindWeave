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

Most tests are pure-logic unit tests with no setup needed. The folder,
item-filing, and chat-persistence tests (`tests/test_folders.py`,
`tests/test_items_folders.py`, `tests/test_chat_persistence.py`) are
integration tests against a real database instead -- consistent with
this project's existing rule of preferring a real DB over mocking one
(see `tests/test_chunking.py`'s docstring) -- so they need a disposable
local Postgres+pgvector instance, separate from your real `.env`
database, and **skip automatically** (not fail) if that instance isn't
running:

```bash
# One-time: start a throwaway test database
docker run -d --name mindweave-test-db -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16

# Stub the `auth` schema/table and auth.uid() that schema.sql expects
# Supabase to provide (real Supabase auth isn't needed for these tests --
# they call the service functions directly with a user_id, bypassing RLS)
docker exec -i mindweave-test-db psql -U postgres -d postgres <<'SQL'
create schema if not exists auth;
create extension if not exists pgcrypto;
create table if not exists auth.users (id uuid primary key default gen_random_uuid());
create or replace function auth.uid() returns uuid as $$ select null::uuid $$ language sql stable;
SQL

# Apply the real schema
docker exec -i mindweave-test-db psql -U postgres -d postgres < db/schema.sql

# Then just run pytest as normal -- it finds the test DB at
# postgresql+asyncpg://postgres:test@localhost:55432/postgres by default
# (override with the TEST_DATABASE_URL env var if you used a different port)
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

## Deploying safely

A few things that matter once this is reachable by real users on the
internet, not just `localhost`:

- **`--proxy-headers` is required behind any reverse proxy** (Render,
  Fly, nginx, etc). Rate limiting (`slowapi`) keys off the caller's IP
  address via `request.client.host`. Behind a reverse proxy, that's the
  *proxy's* IP for every single request unless the proxy's real-IP
  headers are trusted -- which would mean every user shares one rate
  limit bucket, so one active user could lock everyone else out. Start
  uvicorn with:

  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
  ```

  `--forwarded-allow-ips='*'` is safe specifically because a PaaS like
  Render guarantees its own edge proxy is the only thing that can reach
  your app's port directly -- there's no path for an external client to
  forge these headers themselves.

- **Set `CORS_ORIGINS` to your real deployed frontend URL(s)**, comma
  separated if there's more than one (e.g. a Vercel preview URL plus
  your production domain). The default (`http://localhost:5173`) only
  works for local development.

- **Set `ENVIRONMENT=production`** -- turns off SQL echo logging
  (`app/database.py`'s engine is configured with `echo=not
  settings.is_production`), which would otherwise print every query
  (including auth-related ones) to your production logs.

- **Daily usage caps exist at two levels**, both configurable via env
  vars if you're on a tight Gemini quota/budget: `MAX_ITEMS_PER_USER_PER_DAY`
  / `MAX_CHAT_MESSAGES_PER_USER_PER_DAY` cap what any one account can do
  in a day, and `MAX_ITEMS_PER_DAY_GLOBAL` / `MAX_CHAT_MESSAGES_PER_DAY_GLOBAL`
  cap the whole app, across every account combined, from exceeding what
  your actual Gemini plan allows in a day even if no single user looks
  abusive on their own. See `app/config.py` for current defaults.

- **File uploads are restricted by type and size** (`_ALLOWED_AUDIO_MIME_TYPES`,
  `_ALLOWED_DOCUMENT_MIME_TYPES`, `_MAX_AUDIO_BYTES`, `_MAX_DOCUMENT_BYTES`
  in `app/routers/items.py`) specifically so an arbitrary or oversized
  file can't burn a Gemini call and bandwidth before being rejected.

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
