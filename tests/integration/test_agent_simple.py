"""
Простой тест агента с Ollama
============================

Проверяет, что можем создать агента и вызвать Ollama через него.
"""

import asyncio
from litellm import acompletion

class SimpleAgent:
    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model
    
    async def ask(self, question: str) -> str:
        try:
            response = await acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"You are {self.name}, a helpful assistant. Be concise."},
                    {"role": "user", "content": question}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"Ошибка при вызове агента: {e}")

async def test_agent():
    print("🤖 Тестирование агента с Ollama")
    
    agent = SimpleAgent("TestAgent", "ollama_chat/qwen2.5")
    print(f"✅ Создан агент: {agent.name}")
    
    # Тест 1: простой вопрос
    question = "What is 2 + 2? Just the number."
    response = await agent.ask(question)
    print(f"Вопрос: {question}")
    print(f"Ответ: {response}")
    
    # Тест 2: русский вопрос
    question2 = "Привет! Как дела?"
    response2 = await agent.ask(question2)
    print(f"Вопрос: {question2}")
    print(f"Ответ: {response2}")
    
    print("🎉 Агент работает с Ollama!")

if __name__ == "__main__":
    asyncio.run(test_agent()) 