"""
Trade Repository (PostgreSQL)
==============================
Persists trade history to PostgreSQL for long-term analysis.

Requirements:
    pip install psycopg[binary] (for asyncio support)
    
Environment Variables:
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DATABASE
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
from decimal import Decimal

logger = logging.getLogger(__name__)

# Attempt to import asyncpg, fall back if unavailable
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logger.warning("⚠️ asyncpg not installed. PostgreSQL persistence disabled.")


class TradeRepository:
    """
    Async PostgreSQL trade repository.
    Falls back to CSV if PostgreSQL is unavailable.
    """

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self._connected = False
        
        # Fallback CSV for when DB is unavailable
        self._fallback_csv = "data/trades_backup.csv"

    async def connect(self):
        """Initialize PostgreSQL connection pool"""
        if not ASYNCPG_AVAILABLE:
            logger.warning("asyncpg not available - using CSV fallback only")
            return False
            
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "polymarket")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DATABASE", "trades")
        
        if not password:
            logger.warning("POSTGRES_PASSWORD not set - using CSV fallback")
            return False
        
        try:
            self.pool = await asyncpg.create_pool(
                host=host,
                port=int(port),
                user=user,
                password=password,
                database=database,
                min_size=1,
                max_size=5
            )
            
            # Create table if not exists
            await self._init_schema()
            
            self._connected = True
            logger.info("✅ PostgreSQL Trade Repository connected")
            return True
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            self._connected = False
            return False

    async def _init_schema(self):
        """Create trades table if not exists"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    trade_id VARCHAR(64) UNIQUE,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    strategy VARCHAR(32),
                    token_id VARCHAR(128),
                    condition_id VARCHAR(128),
                    market_question TEXT,
                    side VARCHAR(8),
                    entry_price DECIMAL(10, 6),
                    exit_price DECIMAL(10, 6),
                    size DECIMAL(12, 2),
                    pnl DECIMAL(12, 4),
                    pnl_pct DECIMAL(8, 4),
                    exit_reason VARCHAR(64),
                    metadata JSONB
                );
                
                CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            """)
            logger.info("📊 Trade schema initialized")

    async def save_trade(self, trade: Dict) -> bool:
        """
        Save a completed trade to PostgreSQL.
        Falls back to CSV if DB unavailable.
        """
        if not self._connected or not self.pool:
            return self._save_to_csv(trade)
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO trades (
                        trade_id, strategy, token_id, condition_id, 
                        market_question, side, entry_price, exit_price,
                        size, pnl, pnl_pct, exit_reason, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (trade_id) DO UPDATE SET
                        exit_price = EXCLUDED.exit_price,
                        pnl = EXCLUDED.pnl,
                        pnl_pct = EXCLUDED.pnl_pct,
                        exit_reason = EXCLUDED.exit_reason
                """,
                    trade.get("trade_id", f"t_{datetime.now().timestamp()}"),
                    trade.get("strategy", "unknown"),
                    trade.get("token_id", ""),
                    trade.get("condition_id", ""),
                    trade.get("market_question", ""),
                    trade.get("side", ""),
                    Decimal(str(trade.get("entry_price", 0))),
                    Decimal(str(trade.get("exit_price", 0))),
                    Decimal(str(trade.get("size", 0))),
                    Decimal(str(trade.get("pnl", 0))),
                    Decimal(str(trade.get("pnl_pct", 0))),
                    trade.get("exit_reason", ""),
                    trade.get("metadata", {})
                )
            logger.debug(f"💾 Trade {trade.get('trade_id')} saved to PostgreSQL")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save trade to PostgreSQL: {e}")
            return self._save_to_csv(trade)

    def _save_to_csv(self, trade: Dict) -> bool:
        """Fallback: Save to CSV"""
        import csv
        try:
            os.makedirs(os.path.dirname(self._fallback_csv), exist_ok=True)
            
            file_exists = os.path.exists(self._fallback_csv)
            
            with open(self._fallback_csv, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'timestamp', 'trade_id', 'strategy', 'token_id',
                    'side', 'entry_price', 'exit_price', 'size', 'pnl', 'pnl_pct'
                ])
                if not file_exists:
                    writer.writeheader()
                    
                writer.writerow({
                    'timestamp': datetime.now().isoformat(),
                    'trade_id': trade.get('trade_id', ''),
                    'strategy': trade.get('strategy', ''),
                    'token_id': trade.get('token_id', ''),
                    'side': trade.get('side', ''),
                    'entry_price': trade.get('entry_price', 0),
                    'exit_price': trade.get('exit_price', 0),
                    'size': trade.get('size', 0),
                    'pnl': trade.get('pnl', 0),
                    'pnl_pct': trade.get('pnl_pct', 0)
                })
            logger.debug(f"💾 Trade saved to CSV fallback: {self._fallback_csv}")
            return True
            
        except Exception as e:
            logger.error(f"❌ CSV fallback also failed: {e}")
            return False

    async def get_trades(
        self,
        strategy: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Query historical trades"""
        if not self._connected or not self.pool:
            logger.warning("PostgreSQL not connected - cannot query")
            return []
            
        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []
            idx = 1
            
            if strategy:
                query += f" AND strategy = ${idx}"
                params.append(strategy)
                idx += 1
                
            if since:
                query += f" AND timestamp >= ${idx}"
                params.append(since)
                idx += 1
                
            query += f" ORDER BY timestamp DESC LIMIT ${idx}"
            params.append(limit)
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"❌ Failed to query trades: {e}")
            return []

    async def get_strategy_summary(self, strategy: str) -> Dict:
        """Get P&L summary for a strategy"""
        if not self._connected or not self.pool:
            return {}
            
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                        SUM(pnl) as total_pnl,
                        AVG(pnl) as avg_pnl,
                        MAX(pnl) as best_trade,
                        MIN(pnl) as worst_trade
                    FROM trades WHERE strategy = $1
                """, strategy)
                return dict(row) if row else {}
                
        except Exception as e:
            logger.error(f"❌ Failed to get strategy summary: {e}")
            return {}

    async def close(self):
        """Close the connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("🎬 PostgreSQL connection pool closed")
