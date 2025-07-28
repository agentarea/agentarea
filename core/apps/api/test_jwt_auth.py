#!/usr/bin/env python3
"""
Test script for JWT authentication middleware.

This script tests the JWT authentication middleware by:
1. Creating test JWT tokens for different providers (WorkOS, Keycloak, Generic OIDC)
2. Making requests to protected endpoints
3. Verifying authentication works correctly
"""

import jwt
import requests
import time
from datetime import datetime, timedelta


def create_test_token(provider="generic", secret="test-secret-key"):
    """Create a test JWT token for testing different providers."""
    # Base payload
    payload = {
        "sub": f"test-user-{provider}-123",
        "name": f"Test User {provider.title()}",
        "email": f"test-{provider}@example.com",
        "exp": int(time.time()) + 3600,  # 1 hour expiration
        "iat": int(time.time()),
        "iss": f"https://test-{provider}-issuer.com",
        "aud": "test-audience"
    }
    
    # Add provider-specific claims
    if provider == "workos":
        payload["org_id"] = "org_test123"
        payload["role"] = "admin"
    elif provider == "keycloak":
        payload["preferred_username"] = f"testuser_{provider}"
        payload["groups"] = ["users", "admins"]
        payload["realm_access"] = {"roles": ["user", "admin"]}
    
    # Create token with a simple secret (for testing only)
    token = jwt.encode(payload, secret, algorithm="HS256")
    
    return token, payload


def test_public_endpoints(base_url):
    """Test public endpoints that should be accessible without authentication."""
    print("Testing public endpoints...")
    
    # Test root endpoint
    response = requests.get(f"{base_url}/")
    print(f"Root endpoint: {response.status_code} - {response.json()}")
    
    # Test health endpoint
    response = requests.get(f"{base_url}/health")
    print(f"Health endpoint: {response.status_code} - {response.json()}")
    
    print()


def test_protected_endpoints(base_url, token, provider_name):
    """Test protected endpoints that require authentication."""
    print(f"Testing protected endpoints with {provider_name} token...")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test protected test endpoint
    response = requests.get(f"{base_url}/v1/protected/test", headers=headers)
    print(f"Protected test endpoint: {response.status_code}")
    if response.status_code == 200:
        print(f"  Response: {response.json()}")
    else:
        print(f"  Error: {response.text}")
    
    # Test user info endpoint
    response = requests.get(f"{base_url}/v1/auth/users/me", headers=headers)
    print(f"User info endpoint: {response.status_code}")
    if response.status_code == 200:
        print(f"  Response: {response.json()}")
    else:
        print(f"  Error: {response.text}")
    
    print()


def test_unauthorized_access(base_url):
    """Test that protected endpoints reject requests without valid tokens."""
    print("Testing unauthorized access...")
    
    # Test protected endpoint without token
    response = requests.get(f"{base_url}/v1/protected/test")
    print(f"Protected endpoint without token: {response.status_code}")
    
    # Test protected endpoint with invalid token
    headers = {"Authorization": "Bearer invalid-token"}
    response = requests.get(f"{base_url}/v1/protected/test", headers=headers)
    print(f"Protected endpoint with invalid token: {response.status_code}")
    
    print()


def main():
    """Main test function."""
    base_url = "http://localhost:8000"
    
    print("JWT Authentication Test Script")
    print("=" * 40)
    print(f"Base URL: {base_url}")
    print()
    
    # Test public endpoints
    test_public_endpoints(base_url)
    
    # Test with different providers
    providers = ["generic", "workos", "keycloak"]
    
    for provider in providers:
        print(f"\n--- Testing with {provider.title()} Provider ---")
        
        # Create test token
        token, payload = create_test_token(provider)
        print(f"Created test token for user: {payload['sub']}")
        print()
        
        # Test protected endpoints
        test_protected_endpoints(base_url, token, provider.title())
    
    # Test unauthorized access
    print("\n--- Testing Unauthorized Access ---")
    test_unauthorized_access(base_url)
    
    print("Test completed!")


if __name__ == "__main__":
    main()
