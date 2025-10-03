#!/usr/bin/env python3
"""
Basic Chatbot Example - Conversation Flow

This script demonstrates how to create and interact with a chatbot agent
using the AgentArea Python client.
"""

import requests
import json
import time
from typing import Dict, Any, Optional

class AgentAreaClient:
    """Simple client for AgentArea API"""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        self.base_url = base_url
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
    
    def create_agent(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent"""
        response = self.session.post(f"{self.base_url}/v1/agents", json=config)
        response.raise_for_status()
        return response.json()
    
    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get agent information"""
        response = self.session.get(f"{self.base_url}/v1/agents/{agent_id}")
        response.raise_for_status()
        return response.json()
    
    def start_conversation(self, agent_id: str, message: str) -> Dict[str, Any]:
        """Start a new conversation with an agent"""
        response = self.session.post(
            f"{self.base_url}/v1/conversations",
            json={"agent_id": agent_id, "message": message}
        )
        response.raise_for_status()
        return response.json()
    
    def send_message(self, conversation_id: str, message: str) -> Dict[str, Any]:
        """Send a message in an existing conversation"""
        response = self.session.post(
            f"{self.base_url}/v1/conversations/{conversation_id}/messages",
            json={"message": message}
        )
        response.raise_for_status()
        return response.json()
    
    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Get conversation history"""
        response = self.session.get(f"{self.base_url}/v1/conversations/{conversation_id}")
        response.raise_for_status()
        return response.json()

def load_agent_config(config_file: str = "agent-config.json") -> Dict[str, Any]:
    """Load agent configuration from JSON file"""
    with open(config_file, 'r') as f:
        return json.load(f)

def print_conversation_message(message: Dict[str, Any]):
    """Pretty print a conversation message"""
    role = message.get('role', 'unknown')
    content = message.get('content', '')
    message.get('timestamp', '')
    
    if role == 'user':
        print(f"\n👤 User: {content}")
    elif role == 'assistant':
        print(f"\n🤖 Agent: {content}")
    else:
        print(f"\n{role}: {content}")

def main():
    """Main example function"""
    
    # Initialize client
    client = AgentAreaClient()
    
    try:
        # Load and create agent
        print("🚀 Creating chatbot agent...")
        agent_config = load_agent_config()
        agent = client.create_agent(agent_config)
        agent_id = agent['id']
        print(f"✅ Created agent: {agent['name']} (ID: {agent_id})")
        
        # Wait for agent to be ready
        print("\n⏳ Waiting for agent to be ready...")
        time.sleep(2)
        
        # Start conversation
        print("\n💬 Starting conversation...")
        conversation = client.start_conversation(
            agent_id=agent_id,
            message="Hello! I'm interested in learning about AgentArea."
        )
        conversation_id = conversation['id']
        
        # Print initial exchange
        for message in conversation.get('messages', []):
            print_conversation_message(message)
        
        # Continue conversation with example questions
        example_questions = [
            "What can AgentArea do for my business?",
            "How do I get started with creating my first agent?",
            "Can agents work together on complex tasks?",
            "What about security and privacy?",
            "I think I need to speak with a human expert about enterprise features."
        ]
        
        for question in example_questions:
            print("\n" + "="*50)
            print(f"👤 User: {question}")
            
            # Send message and get response
            response = client.send_message(conversation_id, question)
            
            # Print agent response
            if 'message' in response:
                print_conversation_message(response['message'])
            
            # Check for escalation
            if response.get('escalated'):
                print("\n⚠️  Conversation escalated to human agent")
                break
            
            # Wait a bit between messages
            time.sleep(1)
        
        # Get final conversation history
        print("\n" + "="*50)
        print("📝 Final conversation summary:")
        final_conversation = client.get_conversation(conversation_id)
        
        print(f"Total messages: {len(final_conversation.get('messages', []))}")
        print(f"Status: {final_conversation.get('status', 'unknown')}")
        print(f"Duration: {final_conversation.get('duration', 'unknown')}")
        
        if final_conversation.get('escalated'):
            print("🔄 Escalated to human agent")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
    except KeyError as e:
        print(f"❌ Missing expected field: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    print("🤖 AgentArea Basic Chatbot Example")
    print("=" * 40)
    
    # Check if AgentArea is running
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✅ AgentArea is running")
            main()
        else:
            print("❌ AgentArea health check failed")
    except requests.exceptions.RequestException:
        print("❌ Cannot connect to AgentArea. Make sure it's running on localhost:8000")
        print("   Run: make dev-up")