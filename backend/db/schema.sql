-- Mindweave database schema.
-- Run this once in the Supabase SQL editor on a fresh project.
-- Supabase ships the pgvector extension by default.

create extension if not exists vector;

-- One row per thing the user saves (a pasted URL or a raw note).
create table if not exists items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    source_type text not null check (source_type in ('url', 'text', 'audio', 'pdf')),
    source_url text,
    title text,
    raw_text text not null,
    created_at timestamptz not null default now()
);

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
alter table items enable row level security;
alter table chunks enable row level security;

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
