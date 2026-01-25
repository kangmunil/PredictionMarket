import json
import logging
import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = "data/knowledge_base.json"

class RevaluationEngine:
    """
    Generalized engine to audit trading theses against 
    expert domain knowledge and external challenges.
    """
    def __init__(self, pnl_tracker, rag_system=None):
        self.pnl_tracker = pnl_tracker
        self.rag_system = rag_system
        self.knowledge_base = self._load_kb()
        
    def _load_kb(self) -> Dict:
        try:
            if os.path.exists(KNOWLEDGE_BASE_PATH):
                with open(KNOWLEDGE_BASE_PATH, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Failed to load knowledge base: {e}")
            return {}

    async def reevaluate_all(self) -> List[Dict]:
        """Audit all active positions in PnLTracker"""
        flags = []
        active_trades = list(self.pnl_tracker.active_trades.values())
        
        for trade in active_trades:
            result = await self.reevaluate_trade(trade)
            if result and result.get("action") != "CONTINUE":
                flags.append(result)
                
        return flags

    async def reevaluate_trade(self, trade) -> Optional[Dict]:
        """
        Runs logic to see if structural constraints or challenges 
        break the current trade thesis.
        """
        metadata = trade.metadata or {}
        thesis = metadata.get("thesis", {})
        challenges = metadata.get("challenges", [])
        group = metadata.get("group", "DEFAULT").upper()
        
        # 1. Structural Check
        # Check if any KB tags apply to this market question or title
        relevant_rules = []
        for tag, rules in self.knowledge_base.items():
            if tag in group or tag in trade.token_id or (thesis and tag in thesis.get("entry_reason", "")):
                relevant_rules.append((tag, rules))

        # 2. Rebuttal/Challenge Processing
        highest_severity = max([c.get("severity", 0) for c in challenges]) if challenges else 0

        # if we have rules or severe challenges, trigger AI audit
        if relevant_rules or highest_severity > 0.5:
            logger.info(f"🔎 [Audit] Auditing {trade.trade_id} ({group}) | Rules: {len(relevant_rules)} | Challenges: {len(challenges)}")
            return await self._run_ai_audit(trade, relevant_rules, challenges)

        return {"trade_id": trade.trade_id, "action": "CONTINUE"}

    async def _run_ai_audit(self, trade, rules, challenges) -> Dict:
        """Use LLM to reconcile Thesis vs Anti-Thesis"""
        if not self.rag_system:
            # Fallback if AI not available
            return {"trade_id": trade.trade_id, "action": "CONTINUE", "note": "AI Audit skipped (No RAG)"}

        prompt = f"""
### MISSION: THESIS RE-EVALUATION
You are a Senior Risk Compliance Officer. Audit the following trade.

**Position Details:**
- Strategy: {trade.strategy}
- Side: {trade.side}
- Market: {trade.token_id}
- Original Thesis: {json.dumps(trade.metadata.get('thesis', {}))}

**Safety Constraints & Challenges:**
"""
        for tag, rule in rules:
            prompt += f"- RELEVANT DOMAIN ({tag}): {json.dumps(rule)}\n"
        
        for chan in challenges:
            prompt += f"- EXTERNAL CHALLENGE ({chan.get('source')}): {chan.get('reasoning')}\n"

        prompt += """
**TASK:**
Decide if the original reasoning is still valid or if it suffers from a "Structural Blind Spot" (missing fundamental context).

**OUTPUT (JSON ONLY):**
{
    "valid": boolean,
    "confidence_remaining": 0.0-1.0,
    "verdict": "REDUCE" | "EXIT" | "CONTINUE",
    "reasoning": "Brief explanation",
    "structural_violation": boolean
}
"""
        try:
            # Re-using RAG's analyze_market_impact logic essentially, but custom prompt
            # For simplicity, we use the raw OpenRouter client if available or RAG's internal
            response = await self.rag_system._call_openrouter_with_fallback(
                model=self.rag_system.analysis_model,
                messages=[{"role": "system", "content": "You are a critical auditor. Return JSON only."},
                          {"role": "user", "content": prompt}],
                temperature=0.1
            )
            
            audit_result = json.loads(response.choices[0].message.content)
            audit_result["trade_id"] = trade.trade_id
            
            action = audit_result.get("verdict", "CONTINUE")
            if action != "CONTINUE":
                 logger.warning(f"🚨 [AUDIT ALERT] {trade.trade_id}: {action} | Reason: {audit_result.get('reasoning')}")
            
            return audit_result
        except Exception as e:
            logger.error(f"Audit failed for {trade.trade_id}: {e}")
            return {"trade_id": trade.trade_id, "action": "CONTINUE", "error": str(e)}

