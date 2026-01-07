"""
Decision Logger - Centralized Logic Explanation
===============================================

Provides a structured way to log the "WHY" behind trading decisions.
Designed to be human-readable and easily parseable.

Author: Swarm Architect
Created: 2026-01-07
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("DecisionLog")

class DecisionLogger:
    def __init__(self, agent_name: str, notifier=None):
        self.agent_name = agent_name
        self.notifier = notifier

    async def log_decision(
        self,
        action: str,
        token: str,
        confidence: float,
        reason: str,
        factors: Dict[str, Any]
    ):
        """
        Log a major trading decision.
        """
        emoji = "🟢" if action in ["BUY", "LONG"] else "🔴" if action in ["SELL", "SHORT"] else "⚪"

        log_msg = (
            f"\n{'='*60}\n"
            f"🧠 [{self.agent_name}] DECISION: {emoji} {action}\n"
            f"{'='*60}\n"
            f"🎯 Target: {token}\n"
            f"📊 Confidence: {confidence:.1%}\n"
            f"📝 Reason: {reason}\n"
            f"🧩 Factors:\n"
        )

        for k, v in factors.items():
            log_msg += f"   - {k}: {v}\n"

        log_msg += f"{ '='*60}\n"

        # Print to console/file
        logger.info(log_msg)

        # Send summarized alert to Telegram if high confidence
        if self.notifier and confidence >= 0.7:
            telegram_msg = (
                f"🧠 *{self.agent_name} Decision*\n"
                f"{emoji} *{action}* `{token}`\n"
                f"📊 Conf: {confidence:.0%}\n"
                f"📝 _{reason}_"
            )
            try:
                await self.notifier.send_message(telegram_msg)
            except:
                pass
