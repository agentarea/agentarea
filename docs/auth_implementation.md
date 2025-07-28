# Authentication Implementation

This document describes the authentication implementation for the AgentArea platform, which uses OIDC (OpenID Connect) through NextAuth.js on the frontend and JWT validation on the backend.

## Architecture Overview

```
User -> Next.js Frontend -> NextAuth.js -> OIDC Provider -> Backend API
                                      -> JWT Middleware -> Protected Endpoints
```

## Frontend Authentication (Next.js + NextAuth.js)

### Configuration

The frontend uses NextAuth.js with multiple OIDC provider configurations:

1. **Environment Variables** (`.env.local`):
   ```env
   NEXTAUTH_URL=http://localhost:3000
   NEXTAUTH_SECRET=your-secret-key-change-in-production
   
   # Generic OIDC Configuration (fallback)
   OIDC_ISSUER=https://your-oidc-provider.com
   OIDC_CLIENT_ID=your-client-id
   OIDC_CLIENT_SECRET=your-client-secret
   
   # WorkOS Configuration
   WORKOS_ISSUER=https://your-workos-issuer.com
   WORKOS_CLIENT_ID=your-workos-client-id
   WORKOS_CLIENT_SECRET=your-workos-client-secret
   
   # Keycloak Configuration
   KEYCLOAK_ISSUER=https://your-keycloak-server.com/realms/your-realm
   KEYCLOAK_CLIENT_ID=your-keycloak-client-id
   KEYCLOAK_CLIENT_SECRET=your-keycloak-client-secret
   ```

2. **NextAuth Configuration** (`pages/api/auth/[...nextauth].ts`):
   - Configured to use multiple OIDC providers (Generic OIDC, WorkOS, Keycloak)
   - Each provider uses PKCE and state checks for security
   - Extends session to include access token
   - Uses JWT strategy for session management

3. **Middleware** (`middleware.ts`):
   - Protects routes using `withAuth`
   - Redirects unauthenticated users to sign-in page

### Usage in Components

```typescript
import { useSession, signIn, signOut } from "next-auth/react";

// Get session information
const { data: session, status } = useSession();

// Access token for API calls
const token = session?.accessToken;

// Sign in/out functions
signIn("oidc");
signOut();
```

### API Client Integration

The API client (`lib/client.ts`) automatically includes the access token in requests:

```typescript
import client from "./client";

// The client automatically adds Authorization header
const { data, error } = await client.GET("/v1/protected-endpoint", {});
```

## Backend Authentication (FastAPI + JWT Middleware)

### JWT Middleware

The backend uses a custom JWT middleware that validates OIDC tokens:

1. **Configuration**:
   - Uses JWKS (JSON Web Key Set) from the OIDC provider to verify tokens
   - Supports RS256 algorithm by default
   - Fetches JWKS from the configured URI

2. **Token Validation**:
   - Extracts Bearer token from Authorization header
   - Verifies token signature using keys from JWKS
   - Extracts user information from token payload
   - Adds user information to request state

3. **Public Routes**:
   - `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`
   - `/static/` and `/v1/auth/` prefixes

### Usage in Endpoints

```python
from fastapi import Request

@app.get("/v1/protected-endpoint")
async def protected_endpoint(request: Request):
    # Access user information from request state
    user_id = request.state.user_id
    user_info = request.state.user
    
    return {"message": f"Hello, user {user_id}!"}
```

## Setup Instructions

### Frontend Setup

1. Configure environment variables in `.env.local`:
   ```env
   NEXTAUTH_URL=http://localhost:3000
   NEXTAUTH_SECRET=your-secret-key-change-in-production
   OIDC_ISSUER=https://your-oidc-provider.com
   OIDC_CLIENT_ID=your-client-id
   OIDC_CLIENT_SECRET=your-client-secret
   ```

2. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

3. Run the development server:
   ```bash
   npm run dev
   ```

### Backend Setup

1. Configure environment variables:
   ```env
   OIDC_JWKS_URI=https://your-oidc-provider.com/.well-known/jwks.json
   OIDC_ALGORITHM=RS256
   ```

2. Install dependencies:
   ```bash
   cd core
   pip install -r requirements.txt
   ```

3. Run the development server:
   ```bash
   uvicorn agentarea_api.main:app --reload
   ```

## Testing Authentication

1. Navigate to `/test-auth` page in the frontend
2. Click "Sign In with OIDC" to authenticate
3. Verify that the access token is displayed
4. Test API calls to protected endpoints

## Security Considerations

1. **Token Storage**: Access tokens are stored in HTTP-only cookies by NextAuth.js
2. **Token Expiration**: Tokens are automatically refreshed by NextAuth.js
3. **CORS**: Configured to allow cross-origin requests from frontend
4. **HTTPS**: Use HTTPS in production environments
5. **Secrets**: Keep secrets secure and rotate them regularly

## Troubleshooting

### Common Issues

1. **"Invalid token" errors**:
   - Verify OIDC provider configuration
   - Check JWKS URI is accessible
   - Ensure token algorithm matches configuration

2. **"Authorization header missing"**:
   - Ensure middleware is properly configured
   - Check that requests include Authorization header

3. **Redirect loops**:
   - Verify NEXTAUTH_URL matches application URL
   - Check public route configuration

### Debugging

1. Enable NextAuth debug mode:
   ```env
   NEXTAUTH_DEBUG=true
   ```

2. Check backend logs for JWT validation errors
3. Use browser developer tools to inspect network requests and headers
