"use client";

import { useUser, useAuth, SignInButton, SignOutButton, SignedIn, SignedOut } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/LoadingSpinner";

export default function TestAuthPage() {
  const { user, isLoaded: userLoaded } = useUser();
  const { isSignedIn, isLoaded: authLoaded } = useAuth();

  if (!userLoaded || !authLoaded) {
    return <LoadingSpinner fullScreen={true} />;
  }

  return (
    <div className="container mx-auto p-8 max-w-4xl">
      <h1 className="text-3xl font-bold mb-8">Authentication Test Page</h1>
      
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Authentication Status</CardTitle>
            <CardDescription>Current authentication state</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <p><strong>Signed In:</strong> {isSignedIn ? "Yes" : "No"}</p>
              <p><strong>User Loaded:</strong> {userLoaded ? "Yes" : "No"}</p>
              <p><strong>Auth Loaded:</strong> {authLoaded ? "Yes" : "No"}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>User Information</CardTitle>
            <CardDescription>Details about the current user</CardDescription>
          </CardHeader>
          <CardContent>
            {user ? (
              <div className="space-y-2">
                <p><strong>Name:</strong> {user.fullName || "Not provided"}</p>
                <p><strong>Email:</strong> {user.emailAddresses[0]?.emailAddress || "Not provided"}</p>
                <p><strong>User ID:</strong> {user.id}</p>
                <p><strong>Created:</strong> {new Date(user.createdAt).toLocaleDateString()}</p>
                <p><strong>Last Sign In:</strong> {user.lastSignInAt ? new Date(user.lastSignInAt).toLocaleDateString() : "Never"}</p>
              </div>
            ) : (
              <p className="text-gray-500">No user information available</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Authentication Actions</CardTitle>
            <CardDescription>Sign in or out</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <SignedOut>
                <div className="space-y-2">
                  <p className="text-sm text-gray-600">You are not signed in</p>
                  <SignInButton>
                    <Button>Sign In</Button>
                  </SignInButton>
                </div>
              </SignedOut>
              
              <SignedIn>
                <div className="space-y-2">
                  <p className="text-sm text-gray-600">You are signed in</p>
                  <SignOutButton>
                    <Button variant="outline">Sign Out</Button>
                  </SignOutButton>
                </div>
              </SignedIn>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>API Token Test</CardTitle>
            <CardDescription>Test API authentication</CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={async () => {
                try {
                  const response = await fetch("/api/auth/token");
                  const data = await response.json();
                  console.log("Token response:", data);
                  alert(`Token retrieved: ${data.token ? "Success" : "Failed"}`);
                } catch (error) {
                  console.error("Error getting token:", error);
                  alert("Error getting token");
                }
              }}
            >
              Test API Token
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="mt-8">
        <Card>
          <CardHeader>
            <CardTitle>Debug Information</CardTitle>
            <CardDescription>Raw user object for debugging</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="bg-gray-100 dark:bg-gray-800 p-4 rounded text-xs overflow-auto">
              {JSON.stringify(user, null, 2)}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
