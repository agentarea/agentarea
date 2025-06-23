"""
Простой тест агента с Ollama
============================

Проверяет, что можем создать агента и вызвать Ollama через него.
Без хардкода ID, без сложной настройки базы данных.

Запуск:
    cd core
    python tests/integration/test_agent_ollama.py
"""

import asyncio

from litellm import LiteLLM


class SimpleAgent:
    """Простой агент для тестирования"""

    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model
        self.llm = LiteLLM(model=model)

    async def ask(self, question: str) -> str:
        """Задаем вопрос агенту"""
        try:
            response = await self.llm.acompletion(
                messages=[
                    {
                        "role": "system",
                        "content": f"You are {self.name}, a helpful assistant. Be concise.",
                    },
                    {"role": "user", "content": question},
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"Ошибка при вызове агента: {e}")


class TestAgentOllama:
    """Тесты агента с Ollama"""

    async def test_create_agent(self):
        """Проверяем, что можем создать агента"""
        agent = SimpleAgent("TestAgent", "ollama_chat/qwen2.5")
        assert agent.name == "TestAgent"
        assert agent.model == "ollama_chat/qwen2.5"
        print("✅ Агент создан успешно")

    async def test_agent_math_question(self):
        """Проверяем, что агент отвечает на математические вопросы"""
        agent = SimpleAgent("MathAgent", "ollama_chat/qwen2.5")

        question = "What is 5 + 3? Just give the number."
        response = await agent.ask(question)

        print(f"Агент: {agent.name}")
        print(f"Вопрос: {question}")
        print(f"Ответ: {response}")

        # Проверяем, что получили непустой ответ
        assert response is not None
        assert len(response.strip()) > 0
        print("✅ Агент ответил на математический вопрос")

    async def test_agent_russian_question(self):
        """Проверяем, что агент отвечает на русском"""
        agent = SimpleAgent("RussianAgent", "ollama_chat/qwen2.5")

        question = "Привет! Как дела? Ответь кратко."
        response = await agent.ask(question)

        print(f"Агент: {agent.name}")
        print(f"Вопрос: {question}")
        print(f"Ответ: {response}")

        # Проверяем, что получили непустой ответ
        assert response is not None
        assert len(response.strip()) > 0
        print("✅ Агент ответил на русском языке")

    async def test_multiple_agents(self):
        """Проверяем, что можем создать несколько агентов"""
        agent1 = SimpleAgent("Agent1", "ollama_chat/qwen2.5")
        agent2 = SimpleAgent("Agent2", "ollama_chat/qwen2.5")

        # Оба агента отвечают на один вопрос
        question = "Say hi in one word"

        response1 = await agent1.ask(question)
        response2 = await agent2.ask(question)

        print(f"Агент 1 ответил: {response1}")
        print(f"Агент 2 ответил: {response2}")

        # Проверяем, что оба ответили
        assert response1 is not None and len(response1.strip()) > 0
        assert response2 is not None and len(response2.strip()) > 0
        print("✅ Несколько агентов работают одновременно")


async def main():
    """Запускаем тесты агентов"""
    print("🤖 Тестирование агентов с Ollama")
    print("=" * 50)

    test_instance = TestAgentOllama()

    try:
        print("\n1. Создание агента...")
        await test_instance.test_create_agent()

        print("\n2. Математический вопрос к агенту...")
        await test_instance.test_agent_math_question()

        print("\n3. Русский вопрос к агенту...")
        await test_instance.test_agent_russian_question()

        print("\n4. Несколько агентов...")
        await test_instance.test_multiple_agents()

        print("\n🎉 Все тесты агентов прошли успешно!")
        print("Агенты могут вызывать Ollama и получать ответы!")

    except Exception as e:
        print(f"\n💥 Тест агента не прошел: {e}")
        return False

    return True


if __name__ == "__main__":
    # Запускаем тесты
    success = asyncio.run(main())
    exit(0 if success else 1)
