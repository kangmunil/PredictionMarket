import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from src.core.rag_memory import get_rag_memory

logger = logging.getLogger(__name__)

class PolyAIAgent:
    """
    AI Trading Agent powered by RAG.
    Analyzes news context using historical patterns.
    """
    def __init__(self):
        self.memory = get_rag_memory()
        
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = "https://openrouter.ai/api/v1" if os.getenv("OPENROUTER_API_KEY") else None
        
        # Model Selection Strategy (Strictly from .env)
        self.model_name = os.getenv("AI_MODEL_ANALYSIS") or os.getenv("AI_MODEL_ENTITY")
        
        if not self.model_name:
            raise ValueError("❌ AI_MODEL_ANALYSIS or AI_MODEL_ENTITY must be set in .env")
            
        logger.info(f"🤖 PolyAI Agent using model: {self.model_name}")
        
        self.llm = ChatOpenAI(
            model=self.model_name,
            temperature=0, # Deterministic output
            openai_api_key=api_key,
            openai_api_base=base_url
        )
        
        self.parser = JsonOutputParser()

    async def analyze_news(self, news_text: str, market_context: str) -> Dict:
        """
        Analyze news and generate a trading signal.
        """
        # 1. Retrieve Historical Context
        similar_events = self.memory.find_similar_events(news_text, n_results=3)
        history_str = "\n".join([
            f"- Event: {e['content']} (Impact: {e['metadata'].get('market_impact', 'Unknown')})" 
            for e in similar_events
        ])

        # 2. Load System Prompt from File
        try:
            # Assuming the script is run from project root, or we find the file relative to this script
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            prompt_path = os.path.join(project_root, ".claude", "agents", "polymarket-trading-agent.md")
            
            with open(prompt_path, "r") as f:
                content = f.read()
                
            # Remove Frontmatter (between first two ---)
            if content.startswith("---"):
                _, _, body = content.split("---", 2)
                system_instruction = body.strip()
            else:
                system_instruction = content.strip()
                
        except Exception as e:
            logger.warning(f"⚠️ Could not load agent prompt from file, using fallback: {e}")
            system_instruction = """
            You are PolyAI, an elite quantitative trader.
            Your goal is to identify +EV (Positive Expected Value) betting opportunities on Polymarket.
            
            Analyze the input news based on historical patterns.
            Compare the current situation with retrieved similar past events.
            """

        # 3. Construct Prompt with JSON Enforcement
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""
            {{system_instruction}}
            
            IMPORTANT: You must strictly output your response in valid JSON format.
            Do not include any markdown formatting (like ```json), just the raw JSON object.
            
            Output strictly in JSON format:
            {{{{
                "signal": "BUY_YES" | "BUY_NO" | "HOLD",
                "confidence": 0.0 to 1.0,
                "reasoning": "Concise explanation citing history and analysis",
                "risk_level": "LOW" | "MEDIUM" | "HIGH"
            }}}}
            """),
            ("user", """
            [Current News]
            {news}
            
            [Market Context]
            {context}
            
            [Historical Precedents (RAG)]
            {history}
            
            What is your trading decision?
            """)
        ])

        # 4. Reasoning
        chain = prompt | self.llm | self.parser
        
        try:
            result = await chain.ainvoke({
                "system_instruction": system_instruction,
                "news": news_text,
                "context": market_context,
                "history": history_str
            })
            
            logger.info(f"🤖 AI Decision: {result['signal']} ({result['confidence']:.2f})")
            return result
            
        except Exception as e:
            logger.error(f"❌ AI Analysis Failed: {e}")
            return {"signal": "HOLD", "reasoning": "Error", "confidence": 0}

    def learn(self, news_text: str, outcome: str, impact: str):
        """Feed new data into memory"""
        self.memory.add_event(news_text, {
            "outcome": outcome,
            "market_impact": impact,
            "date": str(datetime.now().date())
        })
