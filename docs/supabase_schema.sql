-- Enable vector extension for embeddings
create extension if not exists vector;

-- Table to store market events/news memories
create table market_memories (
  id uuid default gen_random_uuid() primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  
  -- Metadata for filtering
  category text not null,       -- e.g., 'Crypto', 'Politics', 'Sports'
  entity text not null,         -- e.g., 'Bitcoin', 'Trump', 'Real Madrid'
  event_type text,              -- e.g., 'Regulation', 'Price Action', 'Injury'
  
  -- The core content and its vector embedding
  content text not null,        -- The news headline or summary
  embedding vector(1536),       -- OpenAI text-embedding-3-small dimension
  
  -- Structured data for analysis
  market_impact jsonb,          
  /* Structure example:
    {
      "price_change_1h": -0.05,
      "outcome": "Win",
      "sentiment_score": -0.8
    }
  */

  source_url text
);

-- Index for fast similarity search
create index on market_memories using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

-- RPC function for similarity search with filters
create or replace function match_memories (
  query_embedding vector(1536),
  match_threshold float,
  match_count int,
  filter_entity text
)
returns table (
  id uuid,
  content text,
  market_impact jsonb,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    market_memories.id,
    market_memories.content,
    market_memories.market_impact,
    1 - (market_memories.embedding <=> query_embedding) as similarity
  from market_memories
  where 1 - (market_memories.embedding <=> query_embedding) > match_threshold
  and market_memories.entity = filter_entity
  order by market_memories.embedding <=> query_embedding
  limit match_count;
end;
$$;