# Authentication & Authorization Implementation

## 🔐 Overview
This document outlines the comprehensive authentication and authorization implementation in AgentArea, including JWT token management, multi-factor authentication, role-based access control, and enterprise security best practices.

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

## 🚀 Enhanced Authentication Flow

### Modern JWT Token-Based Authentication
AgentArea implements a secure, scalable JWT authentication system with refresh tokens and advanced security features:

```python
# Enhanced token generation with security features
async def create_access_token(
    data: dict, 
    expires_delta: Optional[timedelta] = None,
    token_type: str = "access",
    audience: Optional[str] = None
) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Enhanced JWT claims
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,
        "jti": str(uuid4()),  # Unique token ID for revocation
        "typ": token_type,
        "aud": audience or settings.JWT_AUDIENCE,
        "iss": settings.JWT_ISSUER,
        "sub": str(data.get("user_id")),
        "scope": data.get("permissions", []),
        "session_id": data.get("session_id")
    })
    
    encoded_jwt = jwt.encode(
        to_encode, 
        get_current_private_key(), 
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt
```

### Enhanced Login Process with MFA
1. User submits primary credentials (username/password)
2. Server validates credentials and checks MFA requirements
3. If MFA enabled, server sends challenge (TOTP, SMS, or WebAuthn)
4. User provides MFA response
5. Server validates MFA and generates JWT access + refresh tokens
6. Client stores tokens securely and includes access token in requests
7. Server validates token on each protected endpoint with scope checking

```python
@router.post("/login")
async def login(
    credentials: UserCredentials, 
    request: Request,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
) -> TokenResponse:
    # Rate limiting for brute force protection
    await rate_limiter.check_rate_limit(request.client.host, "login")
    
    try:
        # Enhanced user authentication
        user = await authenticate_user(
            db, 
            credentials.username, 
            credentials.password,
            request.client.host
        )
        
        if not user:
            await audit_logger.log_failed_login(credentials.username, request.client.host)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if MFA is required
        if user.mfa_enabled:
            mfa_challenge = await create_mfa_challenge(user)
            return MFAChallengeResponse(
                challenge_id=mfa_challenge.id,
                challenge_type=mfa_challenge.type,
                message="MFA verification required"
            )
        
        # Generate tokens with session management
        session = await create_user_session(user, request)
        tokens = await generate_token_pair(user, session)
        
        await audit_logger.log_successful_login(user.id, request.client.host)
        
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            scope=" ".join(user.permissions)
        )
        
    except Exception as e:
        await audit_logger.log_login_error(credentials.username, str(e))
        raise
```

## 🛡️ Advanced Authorization

### Attribute-Based Access Control (ABAC) with RBAC
AgentArea implements a hybrid ABAC/RBAC system with fine-grained permissions:

```python
class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"      # System administration
    ADMIN = "admin"                  # Organization administration
    MANAGER = "manager"              # Team management
    DEVELOPER = "developer"          # Development access
    ANALYST = "analyst"              # Read/analyze access
    VIEWER = "viewer"                # Read-only access
    API_CLIENT = "api_client"        # Programmatic access

class Permission(str, Enum):
    # Agent permissions
    AGENT_CREATE = "agent:create"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_EXECUTE = "agent:execute"
    
    # MCP Server permissions
    MCP_SERVER_CREATE = "mcp_server:create"
    MCP_SERVER_READ = "mcp_server:read"
    MCP_SERVER_UPDATE = "mcp_server:update"
    MCP_SERVER_DELETE = "mcp_server:delete"
    MCP_SERVER_MANAGE = "mcp_server:manage"
    
    # System permissions
    SYSTEM_ADMIN = "system:admin"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    METRICS_READ = "metrics:read"

# Enhanced permission decorator
def require_permission(permission: Permission, resource_param: Optional[str] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get('current_user')
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )
            
            resource = None
            if resource_param and resource_param in kwargs:
                resource = kwargs[resource_param]
            
            checker = PermissionChecker(current_user, resource)
            
            if not await checker.check_permission(permission):
                await audit_logger.log_permission_denied(
                    current_user.id, permission, resource
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {permission}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

## Testing Authentication

1. Navigate to `/test-auth` page in the frontend
2. Click "Sign In with OIDC" to authenticate
3. Verify that the access token is displayed
4. Test API calls to protected endpoints

## 🔒 Advanced Security Features

### Multi-Factor Authentication (MFA)
AgentArea supports multiple MFA methods for enhanced security:

```python
class MFAMethod(str, Enum):
    TOTP = "totp"          # Time-based One-Time Password (Google Authenticator)
    SMS = "sms"            # SMS-based verification
    EMAIL = "email"        # Email-based verification
    WEBAUTHN = "webauthn"  # WebAuthn/FIDO2 (hardware keys)
    BACKUP_CODES = "backup_codes"  # One-time backup codes

class MFAService:
    async def setup_totp(self, user: User) -> TOTPSetupResponse:
        secret = pyotp.random_base32()
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name="AgentArea"
        )
        
        # Store secret temporarily until verified
        await self.redis_client.setex(
            f"mfa_setup:{user.id}", 
            300,  # 5 minutes
            secret
        )
        
        return TOTPSetupResponse(
            secret=secret,
            qr_code=generate_qr_code(totp_uri),
            backup_codes=await self.generate_backup_codes(user)
        )
```

### Enhanced Password Security
```python
from passlib.context import CryptContext
from passlib.hash import argon2
import secrets
import string

# Use Argon2 for better security
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__memory_cost=65536,  # 64 MB
    argon2__time_cost=3,        # 3 iterations
    argon2__parallelism=1       # 1 thread
)

class PasswordService:
    def validate_password_strength(self, password: str) -> PasswordValidationResult:
        errors = []
        
        if len(password) < self.min_length:
            errors.append(f"Password must be at least {self.min_length} characters")
        
        # Additional validation logic...
        
        return PasswordValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            strength_score=self._calculate_strength_score(password)
        )
```

### Advanced Token Security
Comprehensive token management with security best practices:

```python
class TokenService:
    async def refresh_access_token(self, refresh_token: str) -> TokenPair:
        try:
            # Validate refresh token with token rotation
            payload = jwt.decode(
                refresh_token,
                get_current_public_key(),
                algorithms=[settings.JWT_ALGORITHM]
            )
            
            # Check for token theft and revoke if necessary
            stored_token = await self.redis_client.get(f"refresh_token:{user_id}:{session_id}")
            if not stored_token or stored_token != refresh_token:
                await self.revoke_all_user_tokens(user_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token - all sessions revoked"
                )
            
            # Generate new token pair (token rotation)
            new_tokens = await self.generate_token_pair(user, session)
            
            return new_tokens
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired"
            )
```

## Security Considerations

1. **Token Storage**: Access tokens are stored in HTTP-only cookies by NextAuth.js
2. **Token Expiration**: Tokens are automatically refreshed by NextAuth.js
3. **CORS**: Configured to allow cross-origin requests from frontend
4. **HTTPS**: Use HTTPS in production environments
5. **Secrets**: Keep secrets secure and rotate them regularly

## 🛡️ API Security & Protection

### Advanced Rate Limiting
Multi-tier rate limiting with intelligent threat detection:

```python
class RateLimiter:
    async def check_rate_limit(
        self, 
        identifier: str, 
        action: str, 
        custom_limit: Optional[Tuple[int, int]] = None
    ) -> None:
        limit, window = custom_limit or self.default_limits.get(action, (100, 60))
        
        # Use Redis sorted set for sliding window
        current_count = await self._get_current_count(identifier, action, window)
        
        if current_count >= limit:
            # Check for suspicious patterns
            if await self._is_suspicious_activity(identifier, action):
                await self._trigger_security_alert(identifier, action)
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {action}"
            )
```

### Enhanced CORS & Security Headers
```python
class SecurityHeadersMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Add comprehensive security headers
            headers = {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "Content-Security-Policy": "default-src 'self'"
            }
```

## 📱 Advanced Session Management

### Comprehensive Session Tracking
Enterprise-grade session management with device tracking:

```python
class SessionManager:
    async def create_session(
        self, 
        user: User, 
        request: Request,
        device_info: Optional[DeviceInfo] = None
    ) -> UserSession:
        # Generate device fingerprint and check for suspicious activity
        device_fingerprint = await self._generate_device_fingerprint(request, device_info)
        
        if await self._is_suspicious_login(user, device_fingerprint, location_info):
            await self._trigger_security_alert(user, device_fingerprint, location_info)
        
        # Create session with comprehensive tracking
        session = UserSession(
            id=uuid4(),
            user_id=user.id,
            device_fingerprint=device_fingerprint,
            ip_address=request.client.host,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + self.session_timeout
        )
        
        return session
```

## 📊 Comprehensive Audit Logging

### Advanced Security Event Tracking
Enterprise-grade audit logging with real-time threat detection:

```python
class AuditLogger:
    async def log_authentication_event(
        self,
        event_type: str,
        user_id: Optional[UUID],
        success: bool,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        audit_log = AuditLog(
            event_type=event_type,
            user_id=user_id,
            success=success,
            risk_score=await self._calculate_risk_score(ip_address, user_id, event_type),
            timestamp=datetime.utcnow()
        )
        
        # Stream to real-time monitoring
        await self.event_stream.publish("security_events", audit_log.to_dict())
        
        # Check for threats
        if not success:
            await self._check_for_threats(audit_log)
```

## 🎯 Security Best Practices & Guidelines

### Development Security
1. **Secure Coding Practices**
   - Never log sensitive data (passwords, tokens, PII)
   - Use parameterized queries to prevent SQL injection
   - Follow OWASP Top 10 security guidelines
   - Use static code analysis tools

2. **Configuration Management**
   - Use environment variables for all configuration
   - Never commit secrets to version control
   - Use secret scanning tools in CI/CD

### Production Security
1. **Infrastructure Security**
   - Use HTTPS everywhere with TLS 1.3
   - Implement proper firewall rules
   - Regular vulnerability scanning
   - Implement DDoS protection

2. **Monitoring & Alerting**
   - Real-time security monitoring with SIEM
   - Automated threat detection and response
   - Incident response automation

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
