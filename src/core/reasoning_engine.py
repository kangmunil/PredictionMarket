"""
LLM Reasoning Engine (The Brain)
================================
Implements the R.O.I (Rules, Origin, Incontestable fact) Model.

Components:
1. The Lawyer: Validates UMA Rules & Structural constraints.
2. The Scientist: Validates Statistical Causality.
3. The Judge: Confirms Binary Reality (Resolution).

Author: Swarm Architect
Created: 2026-01-24
"""

import logging
import json
import os
from typing import Dict, Optional, List
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)

class ReasoningAgent(Enum):
    LAWYER = "LAWYER"
    SCIENTIST = "SCIENTIST"
    JUDGE = "JUDGE"

class Verdict(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNCERTAIN = "UNCERTAIN"

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

class LLMReasoningEngine:
    def __init__(self, model_name="gpt-4o"):
        self.model_name = model_name
        self.knowledge_base_path = "data/knowledge_base.json"
        
        # Load Knowledge Base
        self.knowledge_base = self._load_kb()
        
        try:
            self.llm = ChatOpenAI(model=model_name, temperature=0.0)
            logger.info(f"🧠 LLM Reasoning Engine online ({model_name})")
        except Exception as e:
            logger.error(f"❌ Failed to init LLM: {e}")
            self.llm = None

    def _load_kb(self) -> Dict:
        if os.path.exists(self.knowledge_base_path):
            with open(self.knowledge_base_path, 'r') as f:
                return json.load(f)
        return {}

    async def consult(self, agent: ReasoningAgent, context: Dict) -> Dict:
        """
        Main entry point for AI consultation.
        """
        if not self.llm:
            return {"verdict": Verdict.UNCERTAIN, "reason": "LLM Offline"}

        if agent == ReasoningAgent.LAWYER:
            return await self._consult_lawyer(context)
        elif agent == ReasoningAgent.SCIENTIST:
            return await self._consult_scientist(context)
        elif agent == ReasoningAgent.JUDGE:
            return await self._consult_judge(context)
        else:
            return {"verdict": Verdict.UNCERTAIN, "reason": "Unknown Agent"}

    async def _consult_lawyer(self, context: Dict) -> Dict:
        """
        The Lawyer checks for structural violations against the Knowledge Base.
        """
        category = context.get('category', 'GENERAL')
        question = context.get('market_question', 'Unknown')
        profile = context.get('candidate_profile', {})
        
        rules = self.knowledge_base.get(category, {})
        constraints = rules.get('expert_constraints', [])
        
        prompt = f"""
        You are a strict Lawyer for a Prediction Market firm.
        Your job is to VALIDATE if a candidate meets the MANDATORY structural requirements for a specific role.
        
        [Role Category]: {category}
        [Market Question]: {question}
        
        [Hard Constraints (Must Meet ALL)]:
        {json.dumps(constraints, indent=2)}
        
        [Candidate Profile]:
        {json.dumps(profile, indent=2)}
        
        Task:
        1. Check each constraint against the profile.
        2. If ANY constraint is violated, Verdict is REJECTED.
        3. If all are met, Verdict is APPROVED.
        
        Output JSON: {{ "verdict": "APPROVED/REJECTED", "reason": "..." }}
        """
        
        try:
            response = await self.llm.ainvoke([SystemMessage(content=prompt)])
            return self._parse_response(response.content)
        except Exception as e:
            logger.error(f"Lawyer Error: {e}")
            return {"verdict": Verdict.UNCERTAIN, "reason": str(e)}

    async def _consult_scientist(self, context: Dict) -> Dict:
        """
        The Scientist checks for fundamental causality in arbitrage.
        """
        token_a = context.get('token_a')
        token_b = context.get('token_b')
        news_context = context.get('news_context', '')
        
        prompt = f"""
        You are a Data Scientist validating a Statistical Arbitrage signal.
        The price spread between {token_a} and {token_b} has diverged significantly.
        
        [News Context]:
        {news_context}
        
        Task:
        Determine if this divergence is due to:
        A) "NOISE": Random market fluctuation (True Arb Opportunity)
        B) "FUNDAMENTAL_BREAK": One asset has permanently changed (e.g., Hack, Delisting, Lawsuit).
        
        If (B), we must NOT trade closing the spread.
        
        Output JSON: {{ "verdict": "APPROVED (if Noise) / REJECTED (if Fundamental)", "reason": "..." }}
        """
        try:
            response = await self.llm.ainvoke([SystemMessage(content=prompt)])
            return self._parse_response(response.content)
        except Exception as e:
            return {"verdict": Verdict.UNCERTAIN, "reason": str(e)}

    async def _consult_judge(self, context: Dict) -> Dict:
        """
        The Judge confirms reality based on 'Incontestable Facts'.
        """
        criteria = context.get('resolution_criteria')
        live_text = context.get('real_world_feed')
        
        prompt = f"""
        You are a Binary Judge. Your ONLY job is to decide if a condition is met VERBATIM.
        Do not predict. Do not interpret "likely". Only confirm "DONE".
        
        [Resolution Criteria]: "{criteria}"
        [Live Feed]: "{live_text}"
        
        Task:
        Has the criteria been definitively met?
        - YES: Only if explicitly confirmed in past tense.
        - NO: If ongoing, likely, or unconfirmed.
        
        Output JSON: {{ "verdict": "APPROVED (YES) / REJECTED (NO)", "reason": "..." }}
        """
        try:
            response = await self.llm.ainvoke([SystemMessage(content=prompt)])
            return self._parse_response(response.content)
        except Exception as e:
            return {"verdict": Verdict.UNCERTAIN, "reason": str(e)}

    def _parse_response(self, text: str) -> Dict:
        try:
            clean_text = text.strip().replace("```json", "").replace("```", "")
            return json.loads(clean_text)
        except:
            return {"verdict": Verdict.UNCERTAIN, "reason": "Output Parsing Failed"}
