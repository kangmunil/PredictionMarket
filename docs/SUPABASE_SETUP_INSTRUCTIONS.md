# 🗄️ Supabase 설정 가이드

**목적**: News Scalper의 RAG System을 위한 Supabase 데이터베이스 설정

---

## 📋 전제 조건

✅ Supabase 계정 있음
✅ .env에 SUPABASE_URL과 SUPABASE_KEY 설정됨

현재 설정:
```bash
SUPABASE_URL="https://kzgczkqkuhjvkcphaduw.supabase.co"
SUPABASE_KEY="sb_publishable_W-Rpp39_YIxzkQ8Gh266Aw_tKDuBr8a"
```

---

## 🚀 빠른 설정 (5분)

### Step 1: Supabase Dashboard 접속

1. https://supabase.com/dashboard 접속
2. 프로젝트 선택 (URL에 포함된 프로젝트)
3. 왼쪽 메뉴에서 **SQL Editor** 클릭

### Step 2: 스키마 실행

1. SQL Editor에서 "New query" 클릭
2. `setup_supabase_schema.sql` 파일 내용 전체 복사
3. SQL Editor에 붙여넣기
4. **Run** 버튼 클릭 (또는 Cmd+Enter)

### Step 3: 실행 확인

성공하면 다음 테이블들이 생성됩니다:

✅ `news_events` - 뉴스 이벤트 저장
✅ `market_analyses` - AI 분석 결과
✅ `market_reactions` - 과거 시장 반응 패턴
✅ `rag_trades` - RAG 기반 거래 기록

확인 방법:
1. 왼쪽 메뉴 → **Table Editor**
2. 위 4개 테이블이 보이면 성공!

---

## 🔍 스키마 설명

### 1. news_events (뉴스 이벤트)

```sql
CREATE TABLE news_events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    source TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    entities JSONB DEFAULT '[]'::jsonb,
    category TEXT,
    url TEXT,
    sentiment FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**용도**: OpenRouter AI가 추출한 뉴스와 엔티티 저장

### 2. market_analyses (시장 분석)

```sql
CREATE TABLE market_analyses (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT REFERENCES news_events(event_id),
    market_id TEXT NOT NULL,
    market_question TEXT,
    current_price DECIMAL(10, 6),
    suggested_price DECIMAL(10, 6),
    confidence FLOAT,
    reasoning TEXT,
    trade_recommendation TEXT,
    expected_value DECIMAL(10, 6),
    analyzed_at TIMESTAMPTZ DEFAULT NOW()
);
```

**용도**: Claude Sonnet의 시장 영향 분석 결과 저장

### 3. market_reactions (시장 반응)

```sql
CREATE TABLE market_reactions (
    id BIGSERIAL PRIMARY KEY,
    market_id TEXT NOT NULL,
    event_type TEXT,
    price_before DECIMAL(10, 6),
    price_after DECIMAL(10, 6),
    price_change DECIMAL(10, 6),
    volume_change DECIMAL(10, 2),
    time_to_stabilize_hours INT,
    event_summary TEXT,
    occurred_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**용도**: Historical Pattern Learning (유사 이벤트 매칭용)

### 4. rag_trades (RAG 거래)

```sql
CREATE TABLE rag_trades (
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT REFERENCES market_analyses(id),
    market_id TEXT NOT NULL,
    entry_price DECIMAL(10, 6),
    exit_price DECIMAL(10, 6),
    position_size DECIMAL(10, 2),
    pnl DECIMAL(10, 2),
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    status TEXT
);
```

**용도**: RAG 성능 추적 및 백테스팅

---

## ✅ 설정 확인

스키마 실행 후 다음 테스트 실행:

```bash
python3 << 'EOF'
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client

load_dotenv(Path('.env'))

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

print(f"🔗 Connecting to Supabase...")
print(f"   URL: {url}")

client = create_client(url, key)

# Test: Insert dummy news event
test_event = {
    "event_id": "test_123",
    "title": "Test News Event",
    "content": "This is a test",
    "source": "Test Source",
    "published_at": "2026-01-04T12:00:00+00:00",
    "entities": [],
    "category": "crypto"
}

try:
    response = client.table("news_events").insert(test_event).execute()
    print("✅ Supabase connection successful!")
    print(f"   Inserted test event: {response.data}")

    # Cleanup
    client.table("news_events").delete().eq("event_id", "test_123").execute()
    print("✅ Test cleanup complete")

except Exception as e:
    print(f"❌ Error: {e}")
EOF
```

---

## 🚨 문제 해결

### Error: "relation does not exist"

**원인**: 스키마가 실행되지 않음

**해결**:
1. SQL Editor에서 스키마 다시 실행
2. Table Editor에서 테이블 확인

### Error: "permission denied"

**원인**: RLS (Row Level Security) 정책 문제

**해결**:
스키마에 이미 포함되어 있지만, 추가 확인:

```sql
-- 모든 인증된 사용자에게 접근 허용
ALTER TABLE news_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for authenticated users" ON news_events
    FOR ALL USING (auth.role() = 'authenticated');
```

### Error: "Invalid API key"

**원인**: .env의 SUPABASE_KEY가 잘못됨

**해결**:
1. Supabase Dashboard → Settings → API
2. "anon" public key 복사
3. .env의 SUPABASE_KEY 업데이트

---

## 📊 성능 최적화

스키마에 이미 인덱스가 포함되어 있습니다:

```sql
-- News events
CREATE INDEX idx_news_published ON news_events(published_at DESC);
CREATE INDEX idx_news_category ON news_events(category);
CREATE INDEX idx_news_entities ON news_events USING GIN (entities);

-- Market analyses
CREATE INDEX idx_analyses_market ON market_analyses(market_id);
CREATE INDEX idx_analyses_event ON market_analyses(event_id);
CREATE INDEX idx_analyses_time ON market_analyses(analyzed_at DESC);

-- Market reactions
CREATE INDEX idx_reactions_market ON market_reactions(market_id);
CREATE INDEX idx_reactions_type ON market_reactions(event_type);

-- RAG trades
CREATE INDEX idx_trades_status ON rag_trades(status);
CREATE INDEX idx_trades_market ON rag_trades(market_id);
```

---

## ✅ 완료 체크리스트

- [ ] Supabase Dashboard 접속 완료
- [ ] SQL Editor에서 스키마 실행 완료
- [ ] Table Editor에서 4개 테이블 확인
- [ ] Python 테스트 스크립트 실행 성공
- [ ] .env의 SUPABASE_URL/KEY 확인

---

**다음 단계**: RAG System 통합 테스트 실행

**Last Updated**: 2026-01-04
