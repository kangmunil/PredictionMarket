"""
Streamlit Dashboard API Integration
====================================
Provides REST API endpoints for Streamlit dashboard to query system metrics.

This module creates a lightweight FastAPI server that the Streamlit dashboard
connects to for real-time data.
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Swarm Trading Dashboard API",
    version="1.0.0",
    description="Real-time trading metrics for Streamlit dashboard"
)

# Enable CORS for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for response schemas
class SystemStatus(BaseModel):
    mode: str
    uptime_seconds: float
    active_agents: int
    ws_connected: bool

class PnLSummary(BaseModel):
    total_pnl: float
    open_positions: int
    closed_trades: int
    strategy_breakdown: Dict[str, float]

class TradeRecord(BaseModel):
    trade_id: str
    strategy: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    timestamp: str

class RiskStatus(BaseModel):
    multiplier: float
    circuit_breaker: bool
    max_loss_pct: float
    global_mode: str

# Global reference to swarm system (injected at startup)
_swarm_system = None

def set_swarm_system(swarm):
    """Inject swarm system reference for data access"""
    global _swarm_system
    _swarm_system = swarm

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/status", response_model=SystemStatus)
async def get_system_status():
    if not _swarm_system:
        raise HTTPException(status_code=503, detail="Swarm system not initialized")
    
    return SystemStatus(
        mode="DRY RUN" if getattr(_swarm_system.config, "DRY_RUN", True) else "LIVE",
        uptime_seconds=(datetime.now() - _swarm_system.start_time).total_seconds() if hasattr(_swarm_system, 'start_time') else 0,
        active_agents=len([t for t in _swarm_system.tasks if not t.done()]) if hasattr(_swarm_system, 'tasks') else 0,
        ws_connected=getattr(_swarm_system.client, "ws_connected", False)
    )

@app.get("/pnl", response_model=PnLSummary)
async def get_pnl_summary():
    if not _swarm_system:
        raise HTTPException(status_code=503, detail="Swarm system not initialized")
    
    summary = _swarm_system.pnl_tracker.get_summary()
    return PnLSummary(
        total_pnl=summary.get("total_pnl", 0.0),
        open_positions=summary.get("open_positions", 0),
        closed_trades=summary.get("closed_trades", 0),
        strategy_breakdown=summary.get("strategy_breakdown", {})
    )

@app.get("/trades", response_model=List[TradeRecord])
async def get_recent_trades(limit: int = 20):
    if not _swarm_system:
        raise HTTPException(status_code=503, detail="Swarm system not initialized")
    
    history = _swarm_system.pnl_tracker.history[-limit:]
    return [
        TradeRecord(
            trade_id=t.get("trade_id", ""),
            strategy=t.get("strategy", ""),
            side=t.get("side", ""),
            entry_price=t.get("entry_price", 0),
            exit_price=t.get("exit_price"),
            pnl=t.get("pnl"),
            timestamp=t.get("exit_time", "")
        )
        for t in history
    ]

@app.get("/risk", response_model=RiskStatus)
async def get_risk_status():
    if not _swarm_system:
        raise HTTPException(status_code=503, detail="Swarm system not initialized")
    
    risk_status = _swarm_system.risk_manager.get_status()
    global_mode = await _swarm_system.bus.get_global_mode()
    
    return RiskStatus(
        multiplier=risk_status.get("multiplier", 0.25),
        circuit_breaker=risk_status.get("circuit_breaker", False),
        max_loss_pct=risk_status.get("max_loss_pct", 0.05),
        global_mode=global_mode
    )

@app.get("/signals")
async def get_hot_signals(min_sentiment: float = 0.5):
    if not _swarm_system:
        raise HTTPException(status_code=503, detail="Swarm system not initialized")
    
    hot = await _swarm_system.bus.get_hot_tokens(min_sentiment=min_sentiment)
    return {
        k: {
            "sentiment_score": v.sentiment_score,
            "whale_activity": v.whale_activity_score,
            "spread_regime": v.spread_regime
        }
        for k, v in hot.items()
    }

async def start_dashboard_api(swarm_system, port: int = 8080):
    """Start the dashboard API server"""
    set_swarm_system(swarm_system)
    
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning"
    )
    server = uvicorn.Server(config)
    logger.info(f"📊 Dashboard API starting on http://0.0.0.0:{port}")
    await server.serve()


if __name__ == "__main__":
    # For standalone testing
    uvicorn.run(app, host="0.0.0.0", port=8080)
