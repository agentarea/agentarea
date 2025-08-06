import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'

// Define protected routes that require authentication
const isProtectedRoute = createRouteMatcher([
  '/agents(.*)',
  '/mcp-servers(.*)',
  '/tasks(.*)',
  '/workplace(.*)',
  '/dashboard(.*)',
  '/admin(.*)',
  '/settings(.*)',
  '/chat(.*)',
  '/home(.*)',
])

// Define public routes that don't require authentication
const isPublicRoute = createRouteMatcher([
  '/sign-in(.*)',
  '/sign-up(.*)',
  '/api/auth(.*)',
  '/',
])

export default clerkMiddleware((auth, req) => {
  const { userId } = auth()
  
  // Allow public routes without authentication
  if (isPublicRoute(req)) {
    return
  }

  // For protected routes, redirect unauthenticated users to sign-in
  if (isProtectedRoute(req)) {
    if (!userId) {
      const signInUrl = new URL('/sign-in', req.url)
      signInUrl.searchParams.set('redirect_url', req.url)
      return Response.redirect(signInUrl)
    }
    return
  }

  // For unknown routes: if user is not authenticated, let Next.js handle 404 
  // (without main layout), if authenticated, let them through to see 404 with layout
  if (!userId) {
    // Don't protect unknown routes for unauthenticated users
    // This allows Next.js to show a clean 404 page without the main layout
    return
  }
})

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
}