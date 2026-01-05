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
    
    action: str             # BUY_YES, BUY_NO, HOLD
    confidence: int         # 0-100 score

# --- Node Logic ---
class MarketAgent:
    def __init__(self):
        load_dotenv()
        self.memory = MarketMemory()
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0) # Deterministic

    def retrieve_history(self, state: AgentState):
        """Node 1: Search for similar past events"""
        logger.info(f"📚 Searching history for: {state['news_content'][:50]}...")
        
        memories = self.memory.find_similar_events(
            state['entity'], 
            state['news_content']
        )
        return {"similar_memories": memories}

    def analyze_market(self, state: AgentState):
        """Node 2: Reasoning based on history"""
        logger.info("🧠 Analyzing market impact...")
        
        # Prepare context for LLM
        past_context = "No similar past events found."
        if state['similar_memories']:
            past_context = json.dumps([
                {
                    "event": m['content'],
                    "impact": m['market_impact']
                } for m in state['similar_memories']
            ], indent=2)

        prompt = f"""
        You are an expert crypto trader. Analyze this news for Polymarket trading.
        
        [Target]: {state['entity']}
        [News]: "{state['news_content']}"
        [Current Market Price]: {state['current_price']} (Implied Probability)
        
        [Historical Context]:
        {past_context}
        
        Task:
        1. Compare current news with history. Is this a "Sell the news" event or a real pump?
        2. If similar past events caused a drop, but the asset recovered, signal BUY_YES (Mean Reversion).
        3. If it's a structural crash (like FTX), signal BUY_NO.
        
        Output JSON: {{ "reasoning": "...", "action": "BUY_YES/BUY_NO/HOLD", "confidence": 0-100 }}
        """
        
        try:
            response = self.llm.invoke(prompt)
            # Simple parsing (in prod, use structured output)
            content = response.content.replace("```json", "").replace("```", "")
            result = json.loads(content)
            
            return {
                "analysis_reasoning": result['reasoning'],
                "action": result['action'],
                "confidence": result['confidence']
            }
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return {"action": "HOLD", "confidence": 0, "analysis_reasoning": "Error"}

# --- Graph Construction ---
def build_agent():
    bot = MarketAgent()
    workflow = StateGraph(AgentState)
    
    workflow.add_node("historian", bot.retrieve_history)
    workflow.add_node("analyst", bot.analyze_market)
    
    workflow.set_entry_point("historian")
    workflow.add_edge("historian", "analyst")
    workflow.add_edge("analyst", END)
    
    return workflow.compile()