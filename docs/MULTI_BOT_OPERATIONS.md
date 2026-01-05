# Multi-Bot Operations Guide

Complete guide for running 3 specialized bots in production.

---

## 🎯 Bot Overview

| Bot | Strategy | Speed | Resource Usage | Risk Level |
|-----|----------|-------|----------------|------------|
| **ArbHunter** | Pure Arbitrage | <100ms | Low (CPU, Network) | Low (hedged) |
| **PolyAI** | AI + Stat Arb | 5-10min cycles | High (LLM API, Compute) | Medium (high confidence) |
| **EliteMimic** | Copy Trading | Event-driven | Medium (Blockchain listener) | Medium-High (whale dependency) |

---

## 🚀 Deployment Options

### Option A: PM2 (Recommended for Mac/Linux)

**Pros:**
- Simple setup
- Great monitoring UI
- Low overhead
- Easy log management

**Setup:**

```bash
# 1. Install PM2
npm install pm2 -g

# 2. Setup logs directory
chmod +x setup_logs.sh
./setup_logs.sh

# 3. Start all bots
pm2 start ecosystem.config.js

# 4. Monitor
pm2 monit              # Real-time dashboard
pm2 logs               # All logs
pm2 logs ArbHunter     # Specific bot
```

**Management Commands:**

```bash
# Status
pm2 status
pm2 list

# Restart specific bot
pm2 restart ArbHunter
pm2 restart PolyAI
pm2 restart EliteMimic

# Restart all
pm2 restart all

# Stop
pm2 stop ArbHunter
pm2 stop all

# Delete (remove from PM2)
pm2 delete ArbHunter
pm2 delete all

# Save current state (auto-start on reboot)
pm2 save
pm2 startup  # Follow instructions to enable auto-start
```

---

### Option B: Docker Compose (Recommended for Production)

**Pros:**
- Complete isolation
- Resource limits
- Easy deployment
- Reproducible environments

**Setup:**

```bash
# 1. Build images
docker-compose build

# 2. Start all bots
docker-compose up -d

# 3. Monitor
docker-compose logs -f           # All logs
docker-compose logs -f arbhunter # Specific bot
```

**Management Commands:**

```bash
# Status
docker-compose ps

# Restart specific bot
docker-compose restart arbhunter
docker-compose restart polyai
docker-compose restart elitemimic

# Restart all
docker-compose restart

# Stop
docker-compose stop

# Stop and remove
docker-compose down

# Rebuild after code changes
docker-compose up -d --build

# View resource usage
docker stats
```

---

### Option C: Manual (Development/Testing)

Run each bot in separate terminal windows:

```bash
# Terminal 1
python3 run_arbhunter.py

# Terminal 2
python3 run_polyai.py

# Terminal 3
python3 run_elitemimic.py
```

**Use Case:** Testing, debugging, development

---

## 📊 Monitoring & Observability

### PM2 Monitoring

```bash
# Real-time dashboard
pm2 monit

# Web dashboard (optional)
pm2 install pm2-server-monit
pm2 web  # Opens on http://localhost:9615

# Metrics
pm2 describe ArbHunter
```

### Docker Monitoring

```bash
# Resource usage
docker stats

# Container health
docker-compose ps

# Logs (last 100 lines)
docker-compose logs --tail=100 arbhunter

# Follow logs in real-time
docker-compose logs -f --tail=50
```

### Log Files

All bots write to `logs/` directory:

```
logs/
├── arbhunter.log           # ArbHunter main log
├── arbhunter-error.log     # Errors only
├── arbhunter-out.log       # stdout
├── polyai.log
├── polyai-error.log
├── polyai-out.log
├── elitemimic.log
├── elitemimic-error.log
└── elitemimic-out.log
```

**Monitoring logs:**

```bash
# Live tail (all errors)
tail -f logs/*-error.log

# Search for specific event
grep "ARB OPPORTUNITY" logs/arbhunter.log

# Count errors in last hour
grep "ERROR" logs/polyai.log | grep "$(date '+%Y-%m-%d %H')"
```

---

## ⚙️ Configuration & Tuning

### Per-Bot Configuration

Each bot can be tuned by editing its launcher script:

#### ArbHunter (`run_arbhunter.py`)

```python
# Line 55-56: Adjust profit threshold
strategy.min_profit_threshold = 0.005  # 0.5%

# Line 57: Adjust trade size
strategy.default_trade_size = 100.0    # $100 per leg
```

**Recommended Settings:**

| Market Volatility | Threshold | Trade Size |
|-------------------|-----------|------------|
| Low (stable) | 0.003 (0.3%) | $50-100 |
| Medium | 0.005 (0.5%) | $100-200 |
| High (volatile) | 0.007 (0.7%) | $200-500 |

#### PolyAI (`run_polyai.py`)

```python
# Line 37-38: Adjust scan frequency
self.scan_interval_minutes = 5          # Stat arb scan
self.news_check_interval_minutes = 10   # AI news analysis
```

**Recommended Settings:**

| Use Case | Scan Interval | News Interval |
|----------|---------------|---------------|
| Aggressive | 3 min | 5 min |
| Balanced | 5 min | 10 min |
| Conservative | 10 min | 15 min |

#### EliteMimic (`run_elitemimic.py`)

```python
# Line 48-50: Risk parameters
self.min_ai_confidence = 70        # AI approval threshold
self.max_copy_size_usd = 500       # Max $ per trade
self.copy_ratio = 0.5              # Copy 50% of whale's size
```

**Recommended Settings:**

| Risk Profile | AI Confidence | Max Size | Copy Ratio |
|--------------|---------------|----------|------------|
| Conservative | 80% | $200 | 0.3 (30%) |
| Balanced | 70% | $500 | 0.5 (50%) |
| Aggressive | 60% | $1000 | 0.7 (70%) |

---

## 🔒 Security Best Practices

### 1. Environment Variables

**Never commit `.env` file to git!**

```bash
# Check .gitignore includes
.env
*.log
logs/
```

### 2. API Key Rotation

Rotate keys monthly:

```bash
# Update .env with new keys
nano .env

# Restart all bots
pm2 restart all
# or
docker-compose restart
```

### 3. Wallet Security

- Use **dedicated trading wallet** (not main wallet)
- Set **spending limits** on wallet
- Enable **2FA** on all exchanges/APIs
- Keep private keys in **encrypted storage**

### 4. Rate Limiting

Each bot should respect API limits:

| Service | Limit | Bot Strategy |
|---------|-------|--------------|
| Polymarket CLOB | 100 req/min | Use WebSocket (ArbHunter) |
| OpenAI API | Tier-based | Batch requests (PolyAI) |
| NewsAPI | 100 req/day (free) | Cache results |

---

## 🚨 Troubleshooting

### Bot Won't Start

**PM2:**
```bash
# Check logs
pm2 logs ArbHunter --err

# Common issues:
# - Missing dependencies: pip install -r requirements.txt
# - .env not found: Create from .env.example
# - Port conflict: Check if another instance running
```

**Docker:**
```bash
# Check logs
docker-compose logs arbhunter

# Rebuild
docker-compose down
docker-compose up -d --build
```

### High Memory Usage

**PM2:**
```bash
# Check memory
pm2 list

# If > 1GB, restart
pm2 restart PolyAI
```

**Docker:**
```bash
# Check memory
docker stats

# Adjust limits in docker-compose.yml
```

### Missing Opportunities

**ArbHunter:**
1. Check WebSocket connection: `grep "WebSocket" logs/arbhunter.log`
2. Verify low latency: Test with `ping clob.polymarket.com`
3. Increase profit threshold (less selective)

**PolyAI:**
1. Verify Supabase connection
2. Check AI confidence threshold
3. Ensure memory DB has data: `python src/ai/memory_manager.py`

### Excessive API Costs

**PolyAI consuming too much OpenAI credits:**

```python
# In run_polyai.py, increase scan interval
self.scan_interval_minutes = 10  # instead of 5
```

**Cache embeddings** to avoid re-generating:

```python
# In src/ai/memory_manager.py
# TODO: Add embedding cache
```

---

## 📈 Performance Optimization

### 1. Network Optimization

**For ArbHunter (latency critical):**

```bash
# Use dedicated server near Polygon RPC
# Recommended regions:
# - AWS us-east-1
# - Google Cloud us-central1

# Test latency
ping clob.polymarket.com
```

### 2. Database Optimization

**For PolyAI (Supabase):**

1. **Index optimization**: Already done in schema
2. **Connection pooling**: Use connection pool in production
3. **Query limits**: Limit RAG search to top 3 results

### 3. Resource Allocation

**PM2 Resource Limits:**

```javascript
// In ecosystem.config.js
max_memory_restart: "500M"  // ArbHunter
max_memory_restart: "1G"    // PolyAI
```

**Docker Resource Limits:**

```yaml
# In docker-compose.yml
resources:
  limits:
    cpus: '1.0'
    memory: 512M
```

---

## 📊 Success Metrics

### KPIs to Track

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Arbitrage Win Rate** | >70% | `grep "EXECUTED" logs/arbhunter.log | wc -l` |
| **AI Prediction Accuracy** | >65% | Track trades vs outcomes |
| **Copy Trade Success** | >60% | Compare with whale's performance |
| **System Uptime** | >99% | `pm2 list` (restart count) |
| **API Error Rate** | <5% | `grep "ERROR" logs/*.log | wc -l` |

### Daily Health Check

```bash
# 1. Check all bots running
pm2 status

# 2. Check error counts
grep -c "ERROR" logs/*-error.log

# 3. Check trades today
grep "$(date '+%Y-%m-%d')" logs/arbhunter.log | grep "EXECUTED"

# 4. Check memory usage
pm2 list
```

---

## 🔄 Backup & Recovery

### Backup Strategy

**What to backup:**
1. ✅ `.env` (encrypted)
2. ✅ `logs/` (last 7 days)
3. ✅ Supabase data (export monthly)
4. ✅ Trade history (export to CSV)

**Automated backup script:**

```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR="backups/$DATE"

mkdir -p $BACKUP_DIR

# Backup logs
cp -r logs/ $BACKUP_DIR/

# Backup env (encrypted)
gpg --symmetric --cipher-algo AES256 .env -o $BACKUP_DIR/.env.gpg

# Export Supabase (manual or via API)
# python export_supabase.py > $BACKUP_DIR/supabase.json

echo "Backup completed: $BACKUP_DIR"
```

### Disaster Recovery

**If bot crashes:**

```bash
# PM2 auto-restarts (configured in ecosystem.config.js)

# Manual restart
pm2 restart all
```

**If server crashes:**

```bash
# PM2 auto-start on reboot (if configured)
pm2 startup
pm2 save

# Docker auto-restart
# Already configured with: restart: unless-stopped
```

---

## 🎓 Best Practices

### 1. Start Small

- Begin with low trade sizes ($50-100)
- Run for 1 week in test mode
- Gradually increase based on results

### 2. Diversify Risk

- Don't run all 3 bots with same wallet
- Use different wallets for each strategy
- Set position limits per wallet

### 3. Monitor Daily

- Check logs every morning
- Review trade performance
- Adjust thresholds based on results

### 4. Stay Updated

- Monitor Polymarket announcements
- Update dependencies monthly: `pip install -r requirements.txt --upgrade`
- Review and update memory DB quarterly

---

## 📞 Support Checklist

Before asking for help:

- [ ] Checked logs for error messages
- [ ] Verified `.env` has all required keys
- [ ] Confirmed internet connection stable
- [ ] Tested API keys individually
- [ ] Tried restarting the bot
- [ ] Checked if issue is in documentation

---

## 🚀 Quick Reference

### Start All Bots
```bash
pm2 start ecosystem.config.js
```

### Stop All Bots
```bash
pm2 stop all
```

### View Logs
```bash
pm2 logs
```

### Monitor Performance
```bash
pm2 monit
```

### Restart After Config Change
```bash
pm2 restart all
```

---

**Last Updated:** 2026-01-02
**Version:** 1.0
**Status:** Production Ready
