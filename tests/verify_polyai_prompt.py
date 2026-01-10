import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import asyncio

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock environment variables BEFORE importing the module that uses them
os.environ["AI_MODEL_ANALYSIS"] = "gpt-4-turbo"
os.environ["OPENROUTER_API_KEY"] = "sk-fake-key"

from src.strategies.ai_rag_agent import PolyAIAgent

class TestPolyAIPrompt(unittest.TestCase):
    @patch('src.strategies.ai_rag_agent.ChatOpenAI')
    def test_prompt_content(self, mock_llm):
        """Verify that the agent loads the markdown prompt correctly."""
        
        # Setup mock
        mock_instance = MagicMock()
        mock_llm.return_value = mock_instance
        
        # Initialize Agent
        agent = PolyAIAgent()
        
        # Mocking the chain
        mock_chain = MagicMock()
        mock_result = {
            "signal": "HOLD",
            "confidence": 0.5,
            "reasoning": "Test",
            "risk_level": "LOW"
        }
        
        async def async_mock(*args, **kwargs):
            return mock_result
            
        mock_chain.ainvoke.side_effect = async_mock
        
        # We need to patch where the chain is created or invoked. 
        # Since 'chain' is created inside the function, we can patch `ChatPromptTemplate.from_messages`
        # to inspect the messages passed to it.
        
        with patch('src.strategies.ai_rag_agent.ChatPromptTemplate.from_messages') as mock_prompt_tmpl:
            # Create a dummy chain that supports | operator
            mock_prompt_tmpl.return_value.__or__.return_value.__or__.return_value = mock_chain
            
            # Run
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(agent.analyze_news("Test news", "Test context"))
            
            # Verify chain was invoked with the correct system instruction
            mock_chain.ainvoke.assert_called()
            call_args = mock_chain.ainvoke.call_args
            input_dict = call_args[0][0]
            
            self.assertIn("system_instruction", input_dict)
            instruction = input_dict["system_instruction"]
            
            expected_phrase = "You are an elite Polymarket trading specialist"
            
            if expected_phrase in instruction:
                print("✅ SUCCESS: System prompt loaded correctly from markdown file.")
            else:
                print(f"❌ FAILURE: System prompt did not contain expected phrase. Got fallback or wrong content.")
                # print(f"Content: {instruction[:100]}...")
            
            self.assertIn(expected_phrase, instruction)

if __name__ == '__main__':
    unittest.main()
