-- Mindweave database schema.
-- Run this once in the Supabase SQL editor on a fresh project.
-- Supabase ships the pgvector extension by default.

create extension if not exists vector;

-- One row per thing the user saves (a pasted URL or a raw note).
create table if not exists items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    source_type text not null check (source_type in ('url', 'text')),
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

create policy "Users can manage their own items"
    on items
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can manage their own chunks"
    on chunks
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
