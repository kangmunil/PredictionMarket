import os
import json
import logging
from typing import TypedDict, List
from dotenv import load_dotenv

from typing import TypedDict, Annotated, Sequence, List
import operator
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from .memory_manager import MarketMemory

logger = logging.getLogger(__name__)

# State Definition
class AgentState(TypedDict):
    entity: str             # e.g., 'Bitcoin'
    news_content: str       # The breaking news
    current_price: float    # Current Polymarket probability (0.0-1.0)
    
    similar_memories: List[dict] # Retrieved from RAG
    analysis_reasoning: str      # LLM's thought process
    risk_assessment: str         # Risk Manager's evaluation
    
    action: str             # BUY_YES, BUY_NO, HOLD
    confidence: int         # 0-100 score

# --- Node Logic ---
class MarketAgent:
    def __init__(self):
        load_dotenv()
        self.memory = MarketMemory()
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)

    def retrieve_history(self, state: AgentState):
        """Node 1: Search for similar past events"""
        logger.info(f"📚 Searching history for: {state['entity']}")
        memories = self.memory.find_similar_events(state['entity'], state['news_content'])
        return {"similar_memories": memories}

    def analyze_market(self, state: AgentState):
        """Node 2: Reasoning based on history"""
        logger.info("🧠 Analyzing market impact...")
        past_context = "No similar past events found."
        if state['similar_memories']:
            past_context = json.dumps([{
                "event": m['content'], "impact": m['market_impact']
            } for m in state['similar_memories']], indent=2)

        prompt = f"""
        You are a Senior Crypto Analyst. Based on this news and historical context, predict the outcome.
        
        [Target]: {state['entity']}
        [News]: "{state['news_content']}"
        [Current Price]: {state['current_price']}
        
        [Historical Context]:
        {past_context}
        
        Analyze if this is an overreaction or an undervalued event.
        Output JSON: {{ "reasoning": "...", "action": "BUY_YES/BUY_NO/HOLD", "confidence": 0-100 }}
        """
        try:
            response = self.llm.invoke(prompt)
            result = json.loads(response.content.strip("```json").strip("```"))
            return {"analysis_reasoning": result['reasoning'], "action": result['action'], "confidence": result['confidence']}
        except:
            return {"action": "HOLD", "confidence": 0, "analysis_reasoning": "Analysis Error"}

    def assess_risk(self, state: AgentState):
        """Node 3: Final check before execution"""
        logger.info("🛡️ Assessing risk...")
        if state['action'] == "HOLD":
            return {"risk_assessment": "No action, skipping risk check."}

        prompt = f"""
        You are a conservative Risk Manager. Review this trade:
        - Entity: {state['entity']}
        - Action: {state['action']}
        - Logic: {state['analysis_reasoning']}
        - Confidence: {state['confidence']}%
        
        Is this too risky? Check for:
        1. Low confidence (< 70%)
        2. Vague reasoning.
        
        If it's too risky, change action to 'HOLD'.
        Output JSON: {{ "action": "BUY_YES/BUY_NO/HOLD", "risk_note": "..." }}
        """
        try:
            response = self.llm.invoke(prompt)
            result = json.loads(response.content.strip("```json").strip("```"))
            return {"action": result['action'], "risk_assessment": result['risk_note']}
        except:
            return {"action": "HOLD", "risk_assessment": "Risk Evaluation Failed"}

# --- Graph Construction ---
def build_agent():
    bot = MarketAgent()
    workflow = StateGraph(AgentState)
    
    workflow.add_node("historian", bot.retrieve_history)
    workflow.add_node("analyst", bot.analyze_market)
    workflow.add_node("risk_manager", bot.assess_risk)
    
    workflow.set_entry_point("historian")
    workflow.add_edge("historian", "analyst")
    workflow.add_edge("analyst", "risk_manager")
    workflow.add_edge("risk_manager", END)
    
    return workflow.compile()