"""
Azure AI Foundry Postgres Agent Client
This module handles interactions with the postgres-rag-agent in Azure AI Foundry
"""
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient


class PostgresAgent:
    """Client for interacting with Azure AI Foundry Postgres Agent"""
    
    def __init__(self):
        """Initialize the Postgres Agent client"""
        self.endpoint = os.getenv("AZURE_EXISTING_AIPROJECT_ENDPOINT")
        self.agent_name = "postgres-rag-agent"
        self.project_client = None
        self.openai_client = None
        self._initialized = False
        
        # Initialize the client
        self._initialize()
    
    def _initialize(self):
        """Initialize connection to Azure AI Foundry"""
        if not self.endpoint:
            print("[Postgres Agent] ERROR: AZURE_EXISTING_AIPROJECT_ENDPOINT not set")
            return
        
        try:
            print(f"[Postgres Agent] Initializing with endpoint: {self.endpoint}")
            
            # Create project client with DefaultAzureCredential
            self.project_client = AIProjectClient(
                endpoint=self.endpoint,
                credential=DefaultAzureCredential(),
            )
            
            # Get OpenAI client for responses API
            self.openai_client = self.project_client.get_openai_client()
            
            self._initialized = True
            print(f"[Postgres Agent] Successfully initialized. Agent: {self.agent_name}")
            
        except Exception as e:
            print(f"[Postgres Agent] Initialization failed: {type(e).__name__}: {str(e)}")
            self._initialized = False
    
    def is_ready(self):
        """Check if the agent is ready to use"""
        return self._initialized and self.openai_client is not None
    
    def chat(self, message, conversation_history=None):
        """
        Send a message to the Postgres agent and get a response
        
        Args:
            message (str): The user's message
            conversation_history (list, optional): Previous conversation messages
            
        Returns:
            str: The agent's response text
            
        Raises:
            RuntimeError: If the agent is not properly initialized
            Exception: If the API call fails
        """
        if not self.is_ready():
            raise RuntimeError("Postgres Agent is not initialized. Check configuration.")
        
        try:
            # Use Responses API with agent reference
            # The agent has access to PostgreSQL database through its configured tools
            response = self.openai_client.responses.create(
                input=[{"role": "user", "content": message}],
                extra_body={
                    "agent": {
                        "name": self.agent_name,
                        "type": "agent_reference"
                    }
                },
            )
            
            # Extract response text
            if hasattr(response, 'output_text'):
                return response.output_text
            else:
                return str(response)
                
        except Exception as e:
            error_msg = f"Agent call failed: {type(e).__name__}: {str(e)}"
            print(f"[Postgres Agent] {error_msg}")
            raise Exception(error_msg)


# Global instance
_postgres_agent_instance = None


def get_postgres_agent():
    """
    Get or create the global Postgres Agent instance
    
    Returns:
        PostgresAgent: The initialized agent instance
    """
    global _postgres_agent_instance
    
    if _postgres_agent_instance is None:
        _postgres_agent_instance = PostgresAgent()
    
    return _postgres_agent_instance
