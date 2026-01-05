# Agentic RAG System Setup Guide

Complete guide to setting up the AI trading system with vector memory and contextual reasoning.

---

## 📋 Prerequisites

1. **Supabase Account** (Free tier is sufficient for testing)
   - Sign up at: https://supabase.com
   - Create a new project

2. **OpenAI API Key**
   - Get from: https://platform.openai.com/api-keys
   - Minimum: $5 credit for testing

3. **Python 3.9+**
   - Check: `python --version`

---

## 🚀 Step-by-Step Setup

### Step 1: Install Dependencies

```bash
cd /Users/mac/BOT/PredictionMarket
pip install -r requirements.txt
```

**New packages installed:**
- `openai` - For embeddings and LLM reasoning
- `supabase` - Vector database client
- `langgraph` - Multi-agent workflow framework
- `langchain-openai` - LangChain integration
- `feedparser` - Google News RSS parsing

---

### Step 2: Configure Supabase Database

1. **Access Supabase SQL Editor**
   - Go to your project dashboard
   - Click "SQL Editor" in left sidebar

2. **Run the Schema**
   - Copy contents from `docs/supabase_schema.sql`
   - Paste into SQL Editor
   - Click "Run"

3. **Verify Tables Created**
   ```sql
   SELECT * FROM market_memories LIMIT 1;
   ```
   Should return "0 rows" (empty table is expected)

4. **Get API Credentials**
   - Go to Project Settings → API
   - Copy:
     - **Project URL**: `https://xxxxx.supabase.co`
     - **Anon/Public Key**: `eyJhbGc...` (long string)

---

### Step 3: Configure Environment Variables

1. **Create `.env` file** (if not exists)
   ```bash
   cp .env.example .env
   ```

2. **Add Supabase & OpenAI credentials**
   ```bash
   # Supabase (For Agentic RAG Vector DB)
   SUPABASE_URL="https://your-project.supabase.co"
   SUPABASE_KEY="your-anon-key-here"

   # OpenAI (For Embeddings and LLM Reasoning)
   OPENAI_API_KEY="sk-proj-xxxxx"
   ```

3. **Verify Config**
   ```bash
   python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('OpenAI:', bool(os.getenv('OPENAI_API_KEY'))); print('Supabase:', bool(os.getenv('SUPABASE_URL')))"
   ```
   Should output: `OpenAI: True` and `Supabase: True`

---

### Step 4: Test Memory Manager

```bash
cd src/ai
python memory_manager.py
```

**Expected Output:**
```
✅ Supabase Memory DB connected
✅ OpenAI client initialized
✅ Test memory added successfully
🔍 Search Results: 1 found
  - Main goalkeeper Courtois suffers ACL tear... (Similarity: 0.87)
📊 Memory Stats: {'status': 'active', 'total_memories': 1, ...}
```

**If you see errors:**
- `SUPABASE_URL not found` → Check `.env` file
- `Failed to save memory` → Check Supabase SQL schema was run correctly
- `Embedding generation failed` → Verify OpenAI API key has credits

---

### Step 5: Seed Historical Data

This populates the knowledge base with past events.

```bash
cd src/ai
python data_seeder.py
```

**What it does:**
1. Crawls Google News RSS for past 6 months
2. Uses GPT-4o to analyze each news item
3. Stores enriched data in Supabase with embeddings

**Expected runtime:** 5-10 minutes (depending on `max_items` setting)

**Sample Output:**
```
🔍 Crawling Google News: Real Madrid injury (2024-07-01 to 2026-01-02)
✅ Found 23 news items
🔄 Processing: Real Madrid star forward suffers hamstring strain...
✅ Stored memory #1
...
🎉 Seeding Complete: 15/23 memories stored
```

**Cost Estimate:**
- ~$0.30-0.50 for 15-20 news items (GPT-4o + embeddings)

**To customize:**
Edit `data_seeder.py` line 290-310:
```python
crawler.seed_entity(
    entity="Your Entity",
    category="Sports",  # or Crypto, Politics
    queries=["search query 1", "search query 2"],
    days_back=90,  # How far back to search
    max_items=15   # How many to process
)
```

---

### Step 6: Test Agent Brain

```bash
cd src/ai
python agent_brain.py
```

**What it does:**
Runs a simulated scenario:
- Breaking news: Player injury
- Current price: Dropped from 0.70 to 0.58
- Agent analyzes using RAG → LLM reasoning → Risk check

**Expected Output:**
```
🚀 AGENT TEST: Breaking News Analysis
============================================================
Entity: Real Madrid
News: Vinicius Jr. spotted limping...
Current Price: 0.58 (dropped from ~0.70)

📚 [Historian] Searching past events...
    → Found 2 relevant memories

🧠 [Analyst] Analyzing market reaction...
    Decision: BUY_YES (Confidence: 78%)

🛡️ [Risk Manager] Validating...
    ✅ Trade APPROVED: BUY_YES

📊 FINAL DECISION
============================================================
Action: BUY_YES
Confidence: 78%
Target Price: 0.68
Reasoning: Historical data shows similar minor injuries led to
           overreaction. Market dropped 17% vs historical avg of 8%.
           Team won in 3/4 past cases. Mean reversion opportunity.
```

---

### Step 7: Test Full Strategy

```bash
cd src/strategies
python ai_model_v2.py
```

Tests the integrated strategy with two scenarios:
1. News event analysis
2. External signal validation

---

## 🔧 Troubleshooting

### Issue: "No memories found"
**Cause:** Database is empty
**Solution:** Run `data_seeder.py` first

### Issue: "Embedding generation failed"
**Cause:** Invalid OpenAI API key or no credits
**Solution:**
1. Check key: `echo $OPENAI_API_KEY`
2. Verify credits: https://platform.openai.com/usage

### Issue: "match_memories function does not exist"
**Cause:** SQL schema not applied
**Solution:** Re-run `supabase_schema.sql` in Supabase SQL Editor

### Issue: Agent always returns "HOLD"
**Cause:** Confidence threshold not met
**Solution:**
1. Add more diverse training data via `data_seeder.py`
2. Lower threshold in `ai_model_v2.py` (line 31): `self.min_confidence = 60`

---

## 📊 Understanding the System

### Data Flow

```
Breaking News
    ↓
[1. Historian Node]
    ├─→ Convert news to embedding
    ├─→ Search vector DB for similar past events
    └─→ Return top 3 matches
    ↓
[2. Analyst Node]
    ├─→ Compare current vs historical price impact
    ├─→ Detect mean reversion opportunities
    └─→ Generate trade decision
    ↓
[3. Risk Manager Node]
    ├─→ Validate confidence threshold
    ├─→ Check price extremes
    └─→ Approve or block trade
    ↓
Final Action: BUY_YES / BUY_NO / HOLD
```

### Key Files

| File | Purpose |
|------|---------|
| `src/ai/memory_manager.py` | Vector DB CRUD operations |
| `src/ai/data_seeder.py` | Historical data crawler |
| `src/ai/agent_brain.py` | LangGraph reasoning workflow |
| `src/strategies/ai_model_v2.py` | Trading strategy integration |
| `docs/supabase_schema.sql` | Database schema |

---

## 🎯 Next Steps

### Production Deployment

1. **Increase Training Data**
   ```python
   # In data_seeder.py
   crawler.seed_entity(..., days_back=365, max_items=100)
   ```

2. **Add More Entities**
   - Sports: Liverpool, Barcelona, etc.
   - Crypto: Ethereum, Solana, etc.
   - Politics: Election candidates

3. **Real-Time News Integration**
   - Replace manual testing with live news feeds
   - Options: NewsAPI webhooks, Twitter API, RSS polling

4. **Performance Optimization**
   - Switch to HNSW index (faster for large datasets)
   - Cache embeddings to reduce OpenAI costs
   - Batch processing for multiple markets

5. **Integration with Trading Bot**
   ```python
   # In main.py
   from src.strategies.ai_model_v2 import AIModelStrategyV2

   ai_strategy = AIModelStrategyV2(client=poly_client)

   # Use for copy-trade validation
   if await ai_strategy.validate_trade_signal(...):
       execute_trade()
   ```

---

## 💰 Cost Estimates

### Development/Testing (100 news items)
- Embeddings: ~$0.02 (100 items × $0.0002/item)
- GPT-4o analysis: ~$0.30 (100 items × $0.003/item)
- **Total: ~$0.32**

### Production (1000 items + daily updates)
- Initial seeding: ~$3.20
- Daily updates (20 items/day): ~$0.20/day = $6/month
- Query costs: Negligible (embeddings cached)

**Supabase:** Free tier includes:
- 500MB database (sufficient for 10,000+ memories)
- Unlimited vector searches

---

## 📚 Additional Resources

- [Supabase pgvector docs](https://supabase.com/docs/guides/ai/vector-embeddings)
- [LangGraph tutorials](https://python.langchain.com/docs/langgraph)
- [OpenAI embeddings guide](https://platform.openai.com/docs/guides/embeddings)
- [Polymarket strategy docs](./strategy2.md)

---

## ✅ Verification Checklist

- [ ] Supabase project created
- [ ] SQL schema applied
- [ ] `.env` configured with all keys
- [ ] `pip install -r requirements.txt` completed
- [ ] `memory_manager.py` test passed
- [ ] `data_seeder.py` ran successfully (10+ memories)
- [ ] `agent_brain.py` test shows intelligent decisions
- [ ] `ai_model_v2.py` test passes both scenarios

**When all checked:** Your Agentic RAG system is ready! 🎉
