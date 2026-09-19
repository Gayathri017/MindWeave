-- Mindweave database schema.
-- Run this once in the Supabase SQL editor on a fresh project.
-- Supabase ships the pgvector extension by default.

create extension if not exists vector;

-- A folder is a true container, like a filesystem folder, not a tag: each
-- item belongs to at most one. Deleting a folder deletes everything in it
-- (see the items.folder_id foreign key below) -- the same way deleting a
-- folder on disk takes its contents with it.
create table if not exists folders (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now()
);

create index if not exists folders_user_id_idx on folders (user_id);

-- One row per thing the user saves (a pasted URL or a raw note).
create table if not exists items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    source_type text not null check (source_type in ('url', 'text', 'audio', 'document')),
    source_url text,
    title text,
    raw_text text not null,
    -- Structured fields pulled out of a document (receipt line items and
    -- totals, a paper's figures/captions, an invoice's key fields, etc).
    -- Shape varies by document_type, so this is deliberately schemaless --
    -- see DocumentExtraction in app/services/extraction.py for what a
    -- given extraction run can populate here.
    extracted_data jsonb,
    -- Null means "unfiled" -- sits in the main list, not inside any folder.
    folder_id uuid references folders (id) on delete cascade,
    created_at timestamptz not null default now()
);

-- Adds the columns for databases created before these fields existed; a
-- no-op (IF NOT EXISTS) on a fresh database that already has them above.
alter table items add column if not exists extracted_data jsonb;
alter table items add column if not exists folder_id uuid references folders (id) on delete cascade;

create index if not exists items_folder_id_idx on items (folder_id);

-- Widen the allowed source types for databases created before 'document'
-- replaced the never-used 'pdf' value (auto-generated constraint name,
-- per Postgres's <table>_<column>_check convention).
alter table items drop constraint if exists items_source_type_check;
alter table items add constraint items_source_type_check
    check (source_type in ('url', 'text', 'audio', 'document'));

create index if not exists items_user_id_idx on items (user_id);

-- Chunked, embedded pieces of each item, used for retrieval.
create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    item_id uuid not null references items (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    content text not null,
    embedding vector(768) not null,
    created_at timestamptz not null default now()
);

create index if not exists chunks_user_id_idx on chunks (user_id);

-- Approximate nearest-neighbour index for cosine similarity search.
-- Safe to create on an empty table; Supabase starts using it once there's data.
create index if not exists chunks_embedding_idx
    on chunks using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- Row Level Security: a user can only ever see or touch their own rows.
-- This is the safety net behind the app-level filtering in the backend --
-- see app/database.py for how the backend activates it on a direct connection.
alter table folders enable row level security;
alter table items enable row level security;
alter table chunks enable row level security;

drop policy if exists "Users can manage their own folders" on folders;
create policy "Users can manage their own folders"
    on folders
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Postgres has no "create policy if not exists", so we drop first --
-- this makes the whole file safe to re-run from scratch at any time,
-- e.g. after adding new tables in a later phase.
drop policy if exists "Users can manage their own items" on items;
create policy "Users can manage their own items"
    on items
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own chunks" on chunks;
create policy "Users can manage their own chunks"
    on chunks
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Distinct concepts/entities extracted from a user's saved items.
create table if not exists concepts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    unique (user_id, name)
);

create index if not exists concepts_user_id_idx on concepts (user_id);

-- Which item(s) mention which concept -- lets each node trace back to its source(s).
create table if not exists concept_mentions (
    id uuid primary key default gen_random_uuid(),
    concept_id uuid not null references concepts (id) on delete cascade,
    item_id uuid not null references items (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (concept_id, item_id)
);

create index if not exists concept_mentions_user_id_idx on concept_mentions (user_id);

-- Edges between concepts that co-occurred in the same item. Weight grows
-- each time the same pair co-occurs again in a later item -- this is what
-- lets the graph show which ideas keep coming back together over time.
create table if not exists concept_links (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    concept_a_id uuid not null references concepts (id) on delete cascade,
    concept_b_id uuid not null references concepts (id) on delete cascade,
    weight integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- Canonical ordering (a < b) so each unordered pair has exactly one row.
    check (concept_a_id < concept_b_id),
    unique (concept_a_id, concept_b_id)
);

create index if not exists concept_links_user_id_idx on concept_links (user_id);
create index if not exists concept_links_a_idx on concept_links (concept_a_id);
create index if not exists concept_links_b_idx on concept_links (concept_b_id);

alter table concepts enable row level security;
alter table concept_mentions enable row level security;
alter table concept_links enable row level security;

drop policy if exists "Users can manage their own concepts" on concepts;
create policy "Users can manage their own concepts"
    on concepts for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own concept mentions" on concept_mentions;
create policy "Users can manage their own concept mentions"
    on concept_mentions for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own concept links" on concept_links;
create policy "Users can manage their own concept links"
    on concept_links for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- One row per chat turn (a question or an answer), so a folder's chat
-- survives a page refresh instead of living only in browser memory.
-- folder_id null means the global "Ask your mind" thread, which searches
-- every saved item regardless of folder; a non-null folder_id means that
-- folder's own thread, scoped to only its items.
create table if not exists chat_messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    folder_id uuid references folders (id) on delete cascade,
    role text not null check (role in ('user', 'answer')),
    text text not null,
    -- The {id, title} pairs a saved answer cited, so history can still
    -- render clickable citation chips after a reload.
    sources jsonb,
    created_at timestamptz not null default now()
);

create index if not exists chat_messages_user_id_idx on chat_messages (user_id);
create index if not exists chat_messages_folder_id_idx on chat_messages (folder_id);

alter table chat_messages enable row level security;

drop policy if exists "Users can manage their own chat messages" on chat_messages;
create policy "Users can manage their own chat messages"
    on chat_messages
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
