# AgentArea Frontend

This is the frontend application for the AgentArea platform, built with Next.js.

## Features

- Modern React-based user interface
- Authentication with NextAuth.js and multiple OIDC providers
- Real-time communication with the backend API
- Responsive design with Tailwind CSS
- Internationalization support

## Authentication

The frontend uses NextAuth.js for authentication with multiple OIDC (OpenID Connect) providers:

- Generic OIDC (fallback)
- WorkOS
- Keycloak

### Configuration

To configure authentication, set the following environment variables in `.env.local`:

```env
# NextAuth.js Configuration
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=your-secret-key-change-in-production

# Server-side API Configuration (not exposed to browser)
AGENTAREA_API_URL=http://localhost:8000

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

### How It Works

1. **NextAuth.js**: Handles the authentication flow and session management
2. **Multiple OIDC Providers**: Supports authentication with WorkOS, Keycloak, or any generic OIDC provider
3. **API Client**: Automatically includes the access token in API requests
4. **Middleware**: Protects routes that require authentication

### Protected Routes

Routes are protected using Next.js middleware. Unauthenticated users are redirected to the sign-in page.

### Session Management

NextAuth.js manages user sessions using JWT tokens stored in HTTP-only cookies for security.

## Development

### Prerequisites

- Node.js 18+
- npm, yarn, or pnpm

### Installation

```bash
cd frontend
npm install
```

### Running the Development Server

```bash
npm run dev
```

The application will be available at http://localhost:3000

### Running the UI against staging

Staging is a backend with its own data and its own accounts: an API at
`https://api.staging.agentarea.ru` and Kratos at `https://auth.staging.agentarea.ru`.
It has no UI of its own; you run this one locally.

Put this in `.env.local`, then `pnpm dev`. Any port works; `ORY_BROWSER_URL` and
`AGENTAREA_APP_ORIGIN` are the address you open.

```bash
AGENTAREA_API_URL=https://api.staging.agentarea.ru
# Kratos is reached through this app's own /self-service proxy, so its cookies
# land on localhost.
ORY_SDK_URL=https://auth.staging.agentarea.ru
ORY_BROWSER_URL=http://localhost:3000
# Kratos admin is not public: leave AGENTAREA_AUTH_KRATOS_ADMIN_URL unset, and
# member names and avatars fall back to ids.
AGENTAREA_MCP_APPS_ORIGIN=http://127.0.0.1:3000
AGENTAREA_APP_ORIGIN=http://localhost:3000
```

Open that address and register. Sign-in is by password; there is no mail, so no
verification, recovery or email codes, and no MCP OAuth. Agent runs are real:
sandboxes and the LLM gateway are production's. Staging has no platform models
yet, so a new workspace needs a model provider added before its first run.

## Project Structure

```
frontend/
├── src/
│   ├── app/              # App Router pages
│   │   ├── api/          # API routes
│   │   ├── auth/         # Authentication pages
│   │   └── ...           # Other pages
│   ├── components/       # React components
│   ├── lib/              # Utility functions and API client
│   └── pages/            # Pages Router (for NextAuth.js)
│       └── api/
│           └── auth/     # NextAuth.js API routes
├── public/               # Static assets
├── middleware.ts         # Next.js middleware
└── next.config.ts        # Next.js configuration
```

## Testing Authentication

To test the authentication system:

1. Navigate to http://localhost:3000/test-auth
2. Click "Sign In with OIDC", "Sign In with WorkOS", or "Sign In with Keycloak"
3. Complete the authentication flow with your chosen provider
4. Verify that user information and access token are displayed
5. Test API calls to protected endpoints

## Dependencies

Key dependencies include:

- Next.js 14+ - React framework
- NextAuth.js - Authentication library
- Tailwind CSS - Styling framework
- React - UI library
- @hey-api/openapi-ts - Generated API client and schemas

See `package.json` for the complete list of dependencies.
