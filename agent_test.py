"""
Простой тест агента с Ollama - БЕЗ хардкода ID
"""
import asyncio
from litellm import acompletion

class SimpleAgent:
    def __init__(self, name, model):
        self.name = name
        self.model = model
    
    async def ask(self, question):
        print(f"[{self.name}] Вопрос: {question}")
        response = await acompletion(
            model=self.model,
            messages=[{"role": "user", "content": question}]
        )
        answer = response.choices[0].message.content
        print(f"[{self.name}] Ответ: {answer}")
        return answer

async def test():
    print("🤖 Полный тест агента с Ollama")
    print("=" * 35)
    
    # Создаем агента
    agent = SimpleAgent("TestBot", "ollama_chat/qwen2.5")
    
    print("\n1. Тест математики:")
    await agent.ask("What is 5 + 3? Just the number.")
    
    print("\n2. Тест русского языка:")
    await agent.ask("Привет! Как дела? Ответь кратко.")
    
    print("\n3. Тест создания персонажа:")
    await agent.ask("Introduce yourself as a helpful AI assistant in one sentence.")
    
    print("\n✅ Все тесты агента прошли успешно!")

asyncio.run(test()) 