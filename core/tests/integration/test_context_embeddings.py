#!/usr/bin/env python3
"""
Test script for the refactored embedding system using Ollama's nomic-embed-text model.
Tests the full integration: LLM service -> Embedding service -> Context service -> FAISS storage
"""

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock

# Set test environment
os.environ["CONTEXT_PROVIDER"] = "faiss"
os.environ["CONTEXT_EMBEDDING_MODEL_INSTANCE_ID"] = str(uuid.uuid4())
os.environ["CONTEXT_FAISS_INDEX_PATH"] = "./test_data/context_index.faiss"
os.environ["CONTEXT_FAISS_METADATA_PATH"] = "./test_data/context_metadata.json"

# Import after environment setup
from agentarea_common.di.container import DIContainer
from agentarea_context.application.context_service import ContextService
from agentarea_context.domain.enums import ContextType
from agentarea_context.infrastructure.di_container import setup_context_di
from agentarea_llm.application.embedding_service import EmbeddingService
from agentarea_llm.application.provider_service import ProviderService


class MockProviderService:
    """Mock provider service that simulates Ollama model instance details."""

    async def get_model_instance_with_config(self, model_instance_id: uuid.UUID):
        """Return mock config for Ollama nomic-embed-text model."""
        return {
            "instance": MagicMock(),
            "provider_type": "ollama",
            "model_name": "ollama/nomic-embed-text",  # LiteLLM format for Ollama
            "api_key": "ollama",  # Ollama doesn't need API key
            "endpoint_url": "http://localhost:11434",  # Default Ollama endpoint
        }


async def test_embedding_service():
    """Test the embedding service with Ollama."""
    print("🧪 Testing Embedding Service with Ollama...")

    provider_service = MockProviderService()
    embedding_service = EmbeddingService(provider_service)
    model_instance_id = uuid.UUID(os.environ["CONTEXT_EMBEDDING_MODEL_INSTANCE_ID"])

    try:
        # Test embedding generation
        texts = [
            "The user prefers detailed technical explanations",
            "This task involves API integration with REST endpoints",
            "The agent is good at Python programming",
        ]

        print(f"📝 Generating embeddings for {len(texts)} texts...")
        embeddings = await embedding_service.generate_embeddings(texts, model_instance_id)

        print(f"✅ Generated {len(embeddings)} embeddings")
        print(f"📊 Embedding dimensions: {len(embeddings[0])}")

        # Verify embedding properties
        assert len(embeddings) == 3, "Should have 3 embeddings"
        assert all(len(emb) == len(embeddings[0]) for emb in embeddings), (
            "All embeddings should have same dimension"
        )
        assert all(isinstance(val, float) for emb in embeddings for val in emb), (
            "Embeddings should be floats"
        )

        # Test dimension retrieval
        dimension = await embedding_service.get_embedding_dimension(model_instance_id)
        print(f"🔢 Embedding dimension: {dimension}")
        assert dimension == len(embeddings[0]), "Dimension should match actual embedding size"

        print("✅ Embedding service tests passed!\n")
        return True

    except Exception as e:
        print(f"❌ Embedding service test failed: {e}")
        return False


async def test_context_integration():
    """Test full context integration with embeddings."""
    print("🧪 Testing Context Integration...")

    # Clean up test data directory
    test_data_dir = Path("./test_data")
    if test_data_dir.exists():
        import shutil

        shutil.rmtree(test_data_dir)
    test_data_dir.mkdir(exist_ok=True)

    try:
        # Setup DI container with mocks
        container = DIContainer()

        # Register mock provider service
        provider_service = MockProviderService()
        container.register_singleton(ProviderService, provider_service)

        # Register embedding service
        def create_embedding_service():
            return EmbeddingService(provider_service)

        container.register_factory(EmbeddingService, create_embedding_service)

        # Setup context DI
        setup_context_di(container)

        # Get context service
        context_service = container.get(ContextService)

        # Test data
        task_id = uuid.uuid4()
        agent_id = uuid.uuid4()

        print("💾 Storing context entries...")

        # Store various context entries
        contexts_to_store = [
            ("This task involves REST API development", ContextType.FACTUAL, task_id, None),
            ("I specialize in Python web development", ContextType.SEMANTIC, None, agent_id),
            ("User asked for error handling examples", ContextType.EPISODIC, task_id, agent_id),
            ("The API should use authentication headers", ContextType.WORKING, task_id, None),
            ("Agent knowledge of FastAPI patterns", ContextType.SEMANTIC, None, agent_id),
        ]

        stored_ids = []
        for content, ctx_type, tid, aid in contexts_to_store:
            context_id = await context_service.store_context(
                content=content, context_type=ctx_type, task_id=tid, agent_id=aid
            )
            stored_ids.append(context_id)
            print(f"  ✅ Stored: {content[:50]}...")

        print(f"💾 Stored {len(stored_ids)} context entries")

        # Test retrieval with different scopes
        print("\n🔍 Testing context retrieval...")

        # Test 1: Task-specific context
        task_contexts = await context_service.get_context(
            query="API development REST", task_id=task_id, limit=5
        )
        print(f"🎯 Found {len(task_contexts)} task contexts")
        for ctx in task_contexts:
            print(f"  📋 {ctx.content[:50]}... (score: {ctx.score:.3f})")

        # Test 2: Agent-specific context
        agent_contexts = await context_service.get_context(
            query="Python programming skills", agent_id=agent_id, limit=5
        )
        print(f"🤖 Found {len(agent_contexts)} agent contexts")
        for ctx in agent_contexts:
            print(f"  📋 {ctx.content[:50]}... (score: {ctx.score:.3f})")

        # Test 3: Combined hierarchical context
        combined_contexts = await context_service.get_combined_context(
            task_id=task_id, agent_id=agent_id, query="API development with Python", limit=10
        )
        print(f"🔄 Found {len(combined_contexts)} combined contexts")
        for ctx in combined_contexts:
            print(f"  📋 {ctx.content[:50]}... (score: {ctx.score:.3f})")

        print("✅ Context integration tests passed!\n")
        return True

    except Exception as e:
        print(f"❌ Context integration test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_faiss_similarity_search():
    """Test FAISS similarity search functionality."""
    print("🧪 Testing FAISS Similarity Search...")

    try:
        # Setup similar to context integration test
        container = DIContainer()
        provider_service = MockProviderService()
        container.register_singleton(ProviderService, provider_service)

        def create_embedding_service():
            return EmbeddingService(provider_service)

        container.register_factory(EmbeddingService, create_embedding_service)

        setup_context_di(container)
        context_service = container.get(ContextService)

        # Store similar and different contexts
        similar_contexts = [
            "Python web development with Flask framework",
            "Django web application development in Python",
            "FastAPI REST API development with Python",
        ]

        different_contexts = [
            "JavaScript frontend development with React",
            "Database design with PostgreSQL",
            "Machine learning with TensorFlow",
        ]

        print("💾 Storing test contexts...")
        task_id = uuid.uuid4()

        # Store similar contexts
        for content in similar_contexts:
            await context_service.store_context(content, task_id=task_id)
            print(f"  ✅ Stored: {content}")

        # Store different contexts
        for content in different_contexts:
            await context_service.store_context(content, task_id=task_id)
            print(f"  ✅ Stored: {content}")

        # Test similarity search
        print("\n🔍 Testing similarity search...")

        query = "Python web framework development"
        results = await context_service.get_context(query=query, task_id=task_id, limit=6)

        print(f"🔍 Query: '{query}'")
        print(f"📊 Found {len(results)} results (ordered by relevance):")

        for i, ctx in enumerate(results, 1):
            print(f"  {i}. {ctx.content} (score: {ctx.score:.3f})")

        # Verify that Python web development contexts rank higher
        top_results = results[:3]
        python_web_count = sum(
            1 for ctx in top_results if "Python" in ctx.content and "web" in ctx.content
        )

        print(f"\n📈 Top 3 results contain {python_web_count} Python web development contexts")

        if python_web_count >= 2:
            print("✅ Similarity search working correctly!")
            return True
        else:
            print("⚠️  Similarity search may not be working optimally")
            return False

    except Exception as e:
        print(f"❌ FAISS similarity search test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("🚀 Starting Context Embedding System Tests\n")

    # Check Ollama availability
    try:
        import subprocess

        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if "nomic-embed-text" not in result.stdout:
            print("❌ nomic-embed-text model not found. Please run: ollama pull nomic-embed-text")
            return
        print("✅ Ollama and nomic-embed-text model available\n")
    except FileNotFoundError:
        print("❌ Ollama not found. Please install Ollama first.")
        return

    # Run tests
    tests = [
        ("Embedding Service", test_embedding_service),
        ("Context Integration", test_context_integration),
        ("FAISS Similarity Search", test_faiss_similarity_search),
    ]

    results = []
    for test_name, test_func in tests:
        print("=" * 50)
        success = await test_func()
        results.append((test_name, success))
        print()

    # Summary
    print("=" * 50)
    print("🎯 Test Summary:")
    passed = sum(1 for _, success in results if success)
    total = len(results)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status} {test_name}")

    print(f"\n🏆 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! The refactored embedding system is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")


if __name__ == "__main__":
    asyncio.run(main())
