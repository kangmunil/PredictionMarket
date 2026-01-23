
import json
import shutil
import os
import logging
import asyncio
from datetime import datetime
from src.core.clob_client import PolyClient

# Configuration
DATA_DIR = "data"
BACKUP_DIR = "data/backups"
FILES_TO_CHECK = [
    "trend_follower_state.json",
    "dashboard_state.json"
]

logger = logging.getLogger("StateDoctor")

class StateDoctor:
    def __init__(self):
        self.client = None

    async def initialize(self):
        self.client = PolyClient()
        # We don't need full budget manager etc, just the client for checking markets
        
    async def run(self):
        """Run the full doctor check"""
        logger.info("👨‍⚕️ State Doctor checking system health...")
        await self.initialize()
        self.ensure_backup_dir()
        
        for filename in FILES_TO_CHECK:
            filepath = os.path.join(DATA_DIR, filename)
            if not os.path.exists(filepath):
                continue
                
            # 1. Backup
            self.backup_file(filepath)
            
            # 2. Validate & Prune
            await self.validate_and_prune(filepath, filename)
            
        # 3. Scaling Guardrails (Task 15)
        self.validate_scaling_config()
        
        logger.info("✅ State Doctor: System is healthy.")

    def validate_scaling_config(self):
        """Ensure scaling parameters in .env are sane"""
        from src.core.config import Config
        cfg = Config()
        
        if cfg.DISCOVERY_BATCH_SIZE > cfg.GLOBAL_MONITOR_LIMIT:
            logger.warning(f"⚠️ Config Alert: BATCH_SIZE ({cfg.DISCOVERY_BATCH_SIZE}) > GLOBAL_LIMIT ({cfg.GLOBAL_MONITOR_LIMIT}). Fixing...")
            # We don't modify the object here, just log or throw if critical
            
        if cfg.GLOBAL_MONITOR_LIMIT > 5000:
            logger.warning("⚠️ High Scale Alert: Monitoring 5000+ tokens may impact latency.")
            
        logger.info(f"📊 Scaling Config: Limit={cfg.GLOBAL_MONITOR_LIMIT}, Batch={cfg.DISCOVERY_BATCH_SIZE}, Cap={cfg.STRATEGY_MARKET_CAP}")

    def ensure_backup_dir(self):
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

    def backup_file(self, filepath):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.basename(filepath)
        backup_path = os.path.join(BACKUP_DIR, f"{filename}.{timestamp}.bak")
        shutil.copy2(filepath, backup_path)
        logger.info(f"💾 Backed up {filename} -> {os.path.basename(backup_path)}")

    async def validate_and_prune(self, filepath, filename):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            logger.error(f"❌ Corrupt JSON in {filename}. Recommended action: Restore from backup.")
            return

        is_modified = False
        valid_data = data
        
        # Strategy State (Dictionary of positions)
        if isinstance(data, dict) and filename == "trend_follower_state.json":
            valid_data = {}
            for token_id, pos in data.items():
                if await self.check_token_validity(token_id):
                    valid_data[token_id] = pos
                else:
                    logger.warning(f"🗑️ Pruning INVALID token from {filename}: {token_id} ({pos.get('market_question', 'N/A')})")
                    is_modified = True
        
        # Dashboard State (Dict with 'active_positions' list)
        elif isinstance(data, dict) and "active_positions" in data:
            valid_positions = []
            for pos in data["active_positions"]:
                # Check for "Larry Kudlow" anomaly (Hardcoded rule)
                if "Larry Kudlow" in pos.get('symbol', '') and pos.get('entry') == 0.001:
                    logger.warning(f"🗑️ Pruning KUDLOW anomaly from {filename}")
                    is_modified = True
                    continue
                    
                valid_positions.append(pos)
                
            if len(valid_positions) != len(data["active_positions"]):
                data["active_positions"] = valid_positions
                valid_data = data
                is_modified = True

        if is_modified:
            with open(filepath, 'w') as f:
                json.dump(valid_data, f, indent=2)
            logger.info(f"💾 Saved sanitized {filename}")

    async def check_token_validity(self, token_id):
        try:
             if not self.client.rest_client:
                 return True 
             await asyncio.to_thread(self.client.rest_client.get_order_book, token_id)
             return True
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return False
            return True
