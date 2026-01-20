"""
Swarm Trading Dashboard
========================
Real-time monitoring dashboard for the trading swarm system.

Run with: streamlit run dashboard.py
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import time
import os

# Configuration
API_BASE = os.getenv("DASHBOARD_API_URL", "http://localhost:8080")
REFRESH_INTERVAL = 5  # seconds

# Page config
st.set_page_config(
    page_title="Swarm Trading Dashboard",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
    }
    .status-live { color: #00ff88; font-weight: bold; }
    .status-dry { color: #ffa500; font-weight: bold; }
    .status-panic { color: #ff4444; font-weight: bold; animation: blink 1s infinite; }
    @keyframes blink { 50% { opacity: 0.5; } }
    .big-number { font-size: 2.5rem; font-weight: bold; }
    .positive { color: #00ff88; }
    .negative { color: #ff4444; }
</style>
""", unsafe_allow_html=True)


def fetch_api(endpoint: str):
    """Fetch data from dashboard API"""
    try:
        resp = requests.get(f"{API_BASE}{endpoint}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        return None


def render_header():
    """Render page header with status"""
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.title("🐝 Swarm Trading Dashboard")
    
    status = fetch_api("/status")
    if status:
        with col2:
            mode_class = "status-live" if status["mode"] == "LIVE" else "status-dry"
            st.markdown(f"<span class='{mode_class}'>{status['mode']}</span>", unsafe_allow_html=True)
            st.caption(f"Uptime: {status['uptime_seconds']/3600:.1f}h")
        with col3:
            ws_status = "🟢 Connected" if status["ws_connected"] else "🔴 Disconnected"
            st.markdown(ws_status)
            st.caption(f"Active Agents: {status['active_agents']}")
    else:
        with col2:
            st.error("⚠️ API Unreachable")


def render_pnl_metrics():
    """Render P&L summary cards"""
    st.subheader("📊 Portfolio Performance")
    
    pnl = fetch_api("/pnl")
    if not pnl:
        st.warning("Unable to fetch P&L data")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pnl_class = "positive" if pnl["total_pnl"] >= 0 else "negative"
        pnl_sign = "+" if pnl["total_pnl"] >= 0 else ""
        st.metric(
            label="Total P&L",
            value=f"${pnl_sign}{pnl['total_pnl']:.2f}",
            delta=None
        )
    
    with col2:
        st.metric(label="Open Positions", value=pnl["open_positions"])
    
    with col3:
        st.metric(label="Closed Trades", value=pnl["closed_trades"])
    
    with col4:
        win_rate = 0
        if pnl["closed_trades"] > 0:
            # Approximate win rate from strategy breakdown
            wins = sum(1 for v in pnl["strategy_breakdown"].values() if v > 0)
            total = len(pnl["strategy_breakdown"]) or 1
            win_rate = (wins / total) * 100
        st.metric(label="Strategies Profitable", value=f"{int(win_rate)}%")
    
    # Strategy breakdown chart
    if pnl["strategy_breakdown"]:
        df = pd.DataFrame([
            {"Strategy": k, "P&L": v} 
            for k, v in pnl["strategy_breakdown"].items()
        ])
        fig = px.bar(
            df, x="Strategy", y="P&L",
            color="P&L",
            color_continuous_scale=["#ff4444", "#ffff00", "#00ff88"],
            title="Strategy Performance"
        )
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='white'
        )
        st.plotly_chart(fig, use_container_width=True)


def render_risk_status():
    """Render risk management status"""
    st.subheader("🛡️ Risk Status")
    
    risk = fetch_api("/risk")
    if not risk:
        st.warning("Unable to fetch risk data")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(label="Risk Multiplier", value=f"{risk['multiplier']:.2f}x")
    
    with col2:
        breaker_status = "🔴 ACTIVE" if risk["circuit_breaker"] else "🟢 OK"
        st.metric(label="Circuit Breaker", value=breaker_status)
    
    with col3:
        st.metric(label="Max Loss Limit", value=f"{risk['max_loss_pct']*100:.1f}%")
    
    with col4:
        mode = risk["global_mode"]
        mode_color = {
            "NORMAL": "🟢",
            "BULL_FRENZY": "🟡",
            "PANIC_SELL": "🔴"
        }.get(mode, "⚪")
        st.metric(label="Global Mode", value=f"{mode_color} {mode}")


def render_trades_table():
    """Render recent trades table"""
    st.subheader("📝 Recent Trades")
    
    trades = fetch_api("/trades?limit=20")
    if not trades:
        st.info("No recent trades")
        return
    
    df = pd.DataFrame(trades)
    if df.empty:
        st.info("No trades recorded yet")
        return
    
    # Style the dataframe
    def color_pnl(val):
        if val is None:
            return ""
        color = "#00ff88" if val >= 0 else "#ff4444"
        return f"color: {color}"
    
    styled_df = df.style.applymap(color_pnl, subset=["pnl"] if "pnl" in df.columns else [])
    st.dataframe(styled_df, use_container_width=True)


def render_signals_heatmap():
    """Render hot signals visualization"""
    st.subheader("🔥 Hot Signals")
    
    signals = fetch_api("/signals?min_sentiment=0.3")
    if not signals:
        st.info("No hot signals detected")
        return
    
    if not signals:
        st.caption("Waiting for market signals...")
        return
    
    # Create heatmap data
    data = []
    for token, info in signals.items():
        data.append({
            "Token": token[:20],
            "Sentiment": info.get("sentiment_score", 0),
            "Whale Activity": info.get("whale_activity", 0),
            "Spread": info.get("spread_regime", "NORMAL")
        })
    
    df = pd.DataFrame(data)
    
    if not df.empty:
        fig = px.scatter(
            df, x="Sentiment", y="Whale Activity",
            size="Sentiment", color="Spread",
            hover_name="Token",
            title="Signal Distribution"
        )
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='white'
        )
        st.plotly_chart(fig, use_container_width=True)


def render_sidebar():
    """Render sidebar controls"""
    st.sidebar.header("⚙️ Controls")
    
    # Auto-refresh toggle
    auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True)
    
    if auto_refresh:
        refresh_rate = st.sidebar.slider("Refresh rate (s)", 1, 30, 5)
        st.sidebar.caption(f"Next refresh in {refresh_rate}s")
    
    st.sidebar.divider()
    
    # Quick actions
    st.sidebar.header("🚀 Quick Actions")
    if st.sidebar.button("Force Refresh"):
        st.rerun()
    
    st.sidebar.divider()
    
    # System info
    st.sidebar.header("ℹ️ System Info")
    health = fetch_api("/health")
    if health:
        st.sidebar.success(f"API Status: {health['status']}")
        st.sidebar.caption(f"Last check: {health.get('timestamp', 'N/A')}")
    else:
        st.sidebar.error("API Unreachable")
    
    return auto_refresh


def main():
    """Main dashboard entry point"""
    auto_refresh = render_sidebar()
    
    render_header()
    
    st.divider()
    
    # Main content layout
    col1, col2 = st.columns([2, 1])
    
    with col1:
        render_pnl_metrics()
        render_trades_table()
    
    with col2:
        render_risk_status()
        render_signals_heatmap()
    
    # Auto-refresh logic
    if auto_refresh:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()


if __name__ == "__main__":
    main()
