#!/usr/bin/env python3
"""
Test script for the new unified protocol endpoints.

This script tests both the A2A JSON-RPC and REST interfaces to ensure
they're working correctly.
"""

import asyncio
import sys

import httpx
import pytest

# Test configuration
BASE_URL = "http://localhost:8000/v1/protocol"
TIMEOUT = 30.0


@pytest.mark.asyncio
async def test_health_check():
    """Test the health check endpoint."""
    print("🏥 Testing health check...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{BASE_URL}/health")

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Health check passed: {data}")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


@pytest.mark.asyncio
async def test_agent_card():
    """Test agent card discovery."""
    print("🃏 Testing agent card discovery...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{BASE_URL}/agents/demo-agent/card")

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Agent card retrieved: {data['name']}")
                return True
            else:
                print(f"❌ Agent card failed: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Agent card error: {e}")
        return False


@pytest.mark.asyncio
async def test_rest_message():
    """Test REST message endpoint."""
    print("💬 Testing REST message endpoint...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            payload = {
                "agent_id": "demo-agent",
                "user_id": "test-user",
                "message": "Hello, this is a test message!",
                "context_id": "test-context",
                "metadata": {"test": True},
            }

            response = await client.post(f"{BASE_URL}/messages", json=payload)

            if response.status_code == 200:
                data = response.json()
                print(f"✅ REST message sent: {data['id']}")
                print(f"   Status: {data['status']['state']}")
                if data.get("artifacts"):
                    print(f"   Response: {data['artifacts'][0]['parts'][0]['text'][:50]}...")
                return True
            else:
                print(f"❌ REST message failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
    except Exception as e:
        print(f"❌ REST message error: {e}")
        return False


@pytest.mark.asyncio
async def test_jsonrpc_message():
    """Test JSON-RPC message/send endpoint."""
    print("🔗 Testing JSON-RPC message/send...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": "test-rpc-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Hello via JSON-RPC!"}],
                    },
                    "contextId": "rpc-test-context",
                    "metadata": {"protocol": "json-rpc"},
                },
            }

            response = await client.post(f"{BASE_URL}/rpc", json=payload)

            if response.status_code == 200:
                data = response.json()
                if data.get("error"):
                    print(f"❌ JSON-RPC error: {data['error']}")
                    return False
                else:
                    print(f"✅ JSON-RPC message sent: {data['result']['id']}")
                    print(f"   Status: {data['result']['status']['state']}")
                    return True
            else:
                print(f"❌ JSON-RPC message failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
    except Exception as e:
        print(f"❌ JSON-RPC message error: {e}")
        return False


@pytest.mark.asyncio
async def test_jsonrpc_agent_card():
    """Test JSON-RPC agent/authenticatedExtendedCard endpoint."""
    print("🎭 Testing JSON-RPC agent card...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": "test-rpc-2",
                "method": "agent/authenticatedExtendedCard",
                "params": {"metadata": {"test": True}},
            }

            response = await client.post(f"{BASE_URL}/rpc", json=payload)

            if response.status_code == 200:
                data = response.json()
                if data.get("error"):
                    print(f"❌ JSON-RPC agent card error: {data['error']}")
                    return False
                else:
                    print(f"✅ JSON-RPC agent card: {data['result']['name']}")
                    return True
            else:
                print(f"❌ JSON-RPC agent card failed: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ JSON-RPC agent card error: {e}")
        return False


@pytest.mark.asyncio
async def test_streaming():
    """Test streaming endpoint."""
    print("🌊 Testing streaming endpoint...")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            params = {
                "agent_id": "demo-agent",
                "message": "Tell me a short story",
                "context_id": "stream-test",
            }

            async with client.stream(
                "GET", f"{BASE_URL}/messages/stream", params=params
            ) as response:
                if response.status_code == 200:
                    chunks = []
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            chunks.append(chunk)
                            if len(chunks) >= 3:  # Limit for testing
                                break

                    print(f"✅ Streaming worked: received {len(chunks)} chunks")
                    return True
                else:
                    print(f"❌ Streaming failed: {response.status_code}")
                    return False
    except Exception as e:
        print(f"❌ Streaming error: {e}")
        return False


async def main():
    """Run all tests."""
    print("🚀 Starting protocol endpoint tests...\n")

    tests = [
        ("Health Check", test_health_check),
        ("Agent Card Discovery", test_agent_card),
        ("REST Message", test_rest_message),
        ("JSON-RPC Message", test_jsonrpc_message),
        ("JSON-RPC Agent Card", test_jsonrpc_agent_card),
        ("Streaming", test_streaming),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n{'=' * 50}")
        result = await test_func()
        results.append((test_name, result))

    print(f"\n{'=' * 50}")
    print("📊 Test Results:")
    print(f"{'=' * 50}")

    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:<8} {test_name}")
        if result:
            passed += 1

    print(f"\n{passed}/{len(tests)} tests passed")

    if passed == len(tests):
        print("🎉 All tests passed! Protocol endpoints are working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test runner error: {e}")
        sys.exit(1)
