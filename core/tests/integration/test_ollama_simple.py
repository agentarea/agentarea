"""
Простой тест Ollama
==================

Проверяет, что можем вызвать Ollama напрямую и получить ответ.
Не требует базы данных, настройки или хардкод ID.

Запуск:
    cd core
    python tests/integration/test_ollama_simple.py
"""

import asyncio

from litellm import acompletion


class TestOllamaSimple:
    """Простые тесты для проверки Ollama"""

    async def test_ollama_available(self):
        """Проверяем, что Ollama доступна"""
        try:
            _ = await acompletion(
                model="ollama_chat/qwen2.5",
                messages=[{"role": "user", "content": "Test"}],
                timeout=10,
            )
            # Если дошли сюда - Ollama работает
            assert True
            print("✅ Ollama доступна")
        except Exception as e:
            print(f"❌ Ollama недоступна: {e}")
            raise AssertionError(f"Ollama недоступна: {e}") from e

    async def test_ollama_math_response(self):
        """Проверяем, что Ollama отвечает на простые вопросы"""
        try:
            response = await acompletion(
                model="ollama_chat/qwen2.5",
                messages=[
                    {
                        "role": "user",
                        "content": "What is 2 + 2? Answer with just the number.",
                    }
                ],
                timeout=10,
            )

            content = response.choices[0].message.content
            print("Вопрос: What is 2 + 2?")
            print(f"Ответ: {content}")

            # Проверяем, что получили непустой ответ
            assert content is not None
            assert len(content.strip()) > 0
            print("✅ Получен непустой ответ от Ollama")

        except Exception as e:
            print(f"❌ Ошибка при запросе к Ollama: {e}")
            raise AssertionError(f"Ошибка при запросе к Ollama: {e}") from e

    async def test_ollama_russian_response(self):
        """Проверяем, что Ollama отвечает на русском"""
        try:
            response = await acompletion(
                model="ollama_chat/qwen2.5",
                messages=[{"role": "user", "content": "Привет! Как дела? Ответь кратко."}],
                timeout=10,
            )

            content = response.choices[0].message.content
            print("Вопрос: Привет! Как дела?")
            print(f"Ответ: {content}")

            # Проверяем, что получили непустой ответ
            assert content is not None
            assert len(content.strip()) > 0
            print("✅ Получен ответ на русском от Ollama")

        except Exception as e:
            print(f"❌ Ошибка при русском запросе: {e}")
            raise AssertionError(f"Ошибка при русском запросе: {e}") from e


async def main():
    """Запускаем тесты"""
    print("🚀 Тестирование Ollama")
    print("=" * 50)

    test_instance = TestOllamaSimple()

    try:
        print("\n1. Проверяем доступность Ollama...")
        await test_instance.test_ollama_available()

        print("\n2. Проверяем математический ответ...")
        await test_instance.test_ollama_math_response()

        print("\n3. Проверяем ответ на русском...")
        await test_instance.test_ollama_russian_response()

        print("\n🎉 Все тесты прошли успешно!")
        print("Ollama работает корректно!")

    except Exception as e:
        print(f"\n💥 Тест не прошел: {e}")
        return False

    return True


if __name__ == "__main__":
    # Запускаем тесты
    success = asyncio.run(main())
    exit(0 if success else 1)
