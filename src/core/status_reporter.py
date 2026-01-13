import json
import os
import time
from typing import Dict, List, Any
from datetime import datetime
import threading

class StatusReporter:
    """
    Producer: Periodically writes bot state to a JSON file.
    Aggregates data from different threads safely.
    """
    def __init__(self, filepath="data/dashboard_state.json"):
        self.filepath = filepath
        self.state = {
            "last_updated": 0,
            "balance_usdc": 0.0,
            "total_pnl": 0.0,
            "active_positions": [],
            "recent_logs": [],
            "signals": {}
        }
        self.lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)

    def update_metrics(self, balance: float = None, pnl: float = None):
        with self.lock:
            if balance is not None:
                self.state["balance_usdc"] = balance
            if pnl is not None:
                self.state["total_pnl"] = pnl
        self._flush_async()

    def update_active_positions(self, positions: List[Dict]):
        """
        positions list of dicts:
        [{'symbol': 'BTC', 'size': 50, 'pnl': 1.2, 'entry': 0.5, 'current': 0.55}]
        """
        with self.lock:
            self.state["active_positions"] = positions
        self._flush_async()

    def add_log(self, message: str, level: str = "INFO"):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg": message,
            "level": level
        }
        with self.lock:
            # Keep last 50 logs
            self.state["recent_logs"].append(entry)
            if len(self.state["recent_logs"]) > 50:
                self.state["recent_logs"] = self.state["recent_logs"][-50:]
        self._flush_async()

    def update_signal(self, token_id: str, score: float):
        with self.lock:
            self.state["signals"][token_id] = score
        self._flush_async()

    def _flush_async(self):
        # In a real heavy app, this would be a separate thread loop
        # For now, we write on update but throttle heavily?
        # Or just write. JSON dump is fast.
        self.state["last_updated"] = time.time()
        try:
            # Atomic write pattern
            tmp = self.filepath + ".tmp"
            with open(tmp, 'w') as f:
                json.dump(self.state, f)
            os.replace(tmp, self.filepath)
        except Exception:
            pass
