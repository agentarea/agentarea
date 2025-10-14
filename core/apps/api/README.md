# AgentArea API

This is the backend API for the AgentArea platform, built with FastAPI.

## Features

- RESTful API for managing AI agents and tasks
- Real-time communication via WebSockets
- Authentication and authorization with JWT tokens
- Integration with MCP (Model Context Protocol) servers
- Provider and model management system

## Authentication

The API uses JWT (JSON Web Token) authentication for protecting endpoints. The authentication system supports:

1. **Multi-Provider OIDC Integration**: Validates JWT tokens from multiple OpenID Connect providers:
   - Generic OIDC providers
   - WorkOS
   - Keycloak
2. **JWKS Verification**: Uses JSON Web Key Sets to verify token signatures
3. **Public Routes**: Certain endpoints are accessible without authentication

### Protected Endpoints

All endpoints under `/v1/` (except for explicitly public ones) require a valid JWT token in the Authorization header:

```
Authorization: Bearer <jwt-token>
```

### Public Endpoints

The following endpoints are publicly accessible:

- `/` - Root endpoint
- `/health` - Health check
- `/docs` - API documentation (Swagger UI)
- `/redoc` - API documentation (ReDoc)
- `/openapi.json` - OpenAPI schema
- `/static/` - Static files
- `/v1/auth/` - Authentication endpoints

## Development

### Prerequisites

- Python 3.12+
- uv (package manager)

### Installation

```bash
cd core
uv sync
```

### Running the Development Server

```bash
uv run agentarea-api
```

Or with auto-reload:

```bash
uv run uvicorn agentarea_api.main:app --reload
```

### Environment Variables

Create a `.env` file in the `core` directory with the following variables:

```env
# Kratos Authentication Configuration
# Default test values are provided in config/app.py
# Override in production with your Kratos JWKS
KRATOS_JWKS_B64=<base64-encoded-jwks>
KRATOS_ISSUER=https://agentarea.dev
KRATOS_AUDIENCE=agentarea-api

# Database
DATABASE_URL=postgresql://user:password@localhost/dbname

# Other settings...
```

## API Documentation

Once the server is running, you can access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Testing Authentication

To test the authentication system, you can use the provided test script:

```bash
cd core/apps/api
python test_jwt_auth.py
```

This script will:
1. Test public endpoints
2. Create a test JWT token
3. Test protected endpoints with the token
4. Verify unauthorized access is properly rejected

## Project Structure

```
agentarea_api/
├── main.py              # Application entry point
├── api/
│   ├── jwt_middleware.py # JWT authentication middleware
│   ├── v1/
│   │   ├── router.py     # API router
│   │   ├── auth.py       # Authentication endpoints
│   │   ├── protected.py  # Protected test endpoints
│   │   └── ...           # Other API modules
│   └── events/           # Event handling
├── static/               # Static files
└── tests/                # Test files
```

## Dependencies

Key dependencies include:

- FastAPI - Web framework
- PyJWT - JWT handling
- httpx - HTTP client (for JWKS fetching)
- uvicorn - ASGI server

See `pyproject.toml` for the complete list of dependencies.
