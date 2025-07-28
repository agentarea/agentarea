# Clerk Authentication Setup Guide

This guide will help you set up Clerk authentication for the AgentArea frontend application.

## Prerequisites

1. A Clerk account (sign up at [clerk.com](https://clerk.com))
2. Node.js 18+ installed
3. The frontend application running locally

## Step 1: Create a Clerk Application

1. Go to the [Clerk Dashboard](https://dashboard.clerk.com/)
2. Click "Add application"
3. Choose "Next.js" as your framework
4. Give your application a name (e.g., "AgentArea")
5. Select your preferred authentication methods (Email, Google, GitHub, etc.)

## Step 2: Get Your API Keys

1. In your Clerk Dashboard, go to the "API Keys" section
2. Copy your **Publishable Key** (starts with `pk_test_` or `pk_live_`)
3. Copy your **Secret Key** (starts with `sk_test_` or `sk_live_`)

## Step 3: Configure Environment Variables

Create a `.env.local` file in the `frontend` directory with the following variables:

```env
# Clerk Authentication Configuration
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your-publishable-key-here
CLERK_SECRET_KEY=sk_test_your-secret-key-here

# Optional: Custom sign-in/sign-up URLs
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/dashboard
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/dashboard

# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000

# Development Settings
NODE_ENV=development
```

## Step 4: Configure Clerk Application Settings

1. In your Clerk Dashboard, go to "User & Authentication" → "Email, Phone, Username"
2. Configure your preferred authentication methods
3. Go to "Paths" and set:
   - Sign-in URL: `/sign-in`
   - Sign-up URL: `/sign-up`
   - After sign-in URL: `/dashboard`
   - After sign-up URL: `/dashboard`

## Step 5: Test the Integration

1. Start your development server:
   ```bash
   cd frontend
   npm run dev
   ```

2. Navigate to `http://localhost:3000`
3. You should see the sign-in/sign-up buttons in the header
4. Test the authentication flow

## Step 6: Backend Integration

The backend is already configured to work with Clerk. Make sure your backend environment variables include:

```env
# Clerk Configuration for Backend
CLERK_ISSUER=https://your-clerk-issuer.clerk.accounts.dev
CLERK_JWKS_URL=https://your-clerk-issuer.clerk.accounts.dev/.well-known/jwks.json
CLERK_AUDIENCE=your-api-audience
```

## Features Implemented

### ✅ Authentication Components
- **Sign In Page**: `/sign-in` with Clerk's SignIn component
- **Sign Up Page**: `/sign-up` with Clerk's SignUp component
- **User Profile**: Integrated with Clerk's UserButton component
- **Sign Out**: Integrated with Clerk's SignOutButton component

### ✅ Middleware Protection
- **Route Protection**: All routes are protected by Clerk middleware
- **API Protection**: API routes are protected
- **Static Files**: Static files are excluded from protection

### ✅ User Interface
- **User Block**: Shows authenticated user information
- **Loading States**: Proper loading states during authentication
- **Error Handling**: Graceful error handling for authentication failures

### ✅ API Integration
- **Token Management**: Automatic token retrieval for API calls
- **Authorization Headers**: Automatic inclusion of Bearer tokens
- **401 Handling**: Automatic redirect to sign-in on 401 responses

## Usage Examples

### Protecting Routes

```tsx
import AuthGuard from "@/components/auth/AuthGuard";

export default function ProtectedPage() {
  return (
    <AuthGuard>
      <div>This content is only visible to authenticated users</div>
    </AuthGuard>
  );
}
```

### Using User Data

```tsx
import { useUser } from "@clerk/nextjs";

export default function UserProfile() {
  const { user, isLoaded } = useUser();

  if (!isLoaded) return <div>Loading...</div>;

  return (
    <div>
      <h1>Welcome, {user?.fullName}!</h1>
      <p>Email: {user?.emailAddresses[0]?.emailAddress}</p>
    </div>
  );
}
```

### Conditional Rendering

```tsx
import { SignedIn, SignedOut } from "@clerk/nextjs";

export default function HomePage() {
  return (
    <div>
      <SignedIn>
        <p>Welcome back! You are signed in.</p>
      </SignedIn>
      <SignedOut>
        <p>Please sign in to continue.</p>
      </SignedOut>
    </div>
  );
}
```

## Troubleshooting

### Common Issues

1. **"Clerk not initialized" error**
   - Make sure your environment variables are set correctly
   - Restart your development server after adding environment variables

2. **Authentication not working**
   - Check that your Clerk application is properly configured
   - Verify your API keys are correct
   - Check the browser console for any errors

3. **API calls failing**
   - Ensure the backend is configured with the correct Clerk settings
   - Check that the token is being sent in the Authorization header

4. **Styling issues**
   - The Clerk components are styled to match your application's theme
   - You can customize the appearance in the ClerkProvider configuration

### Debug Mode

To enable debug mode, add this to your `.env.local`:

```env
NEXT_PUBLIC_CLERK_DEBUG=true
```

## Security Considerations

1. **Environment Variables**: Never commit your `.env.local` file to version control
2. **API Keys**: Keep your Clerk secret key secure and only use it on the server side
3. **HTTPS**: Use HTTPS in production for secure authentication
4. **Session Management**: Clerk handles session management securely

## Next Steps

1. **Customize Appearance**: Modify the ClerkProvider appearance to match your brand
2. **Add Social Providers**: Configure additional authentication providers in your Clerk dashboard
3. **Implement Role-Based Access**: Use Clerk's user metadata for role-based access control
4. **Add Multi-Factor Authentication**: Enable MFA in your Clerk dashboard for enhanced security

## Support

- [Clerk Documentation](https://clerk.com/docs)
- [Clerk Community](https://clerk.com/community)
- [Clerk Support](https://clerk.com/support) 