"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { AuthLayout } from "@/components/auth/auth-layout";

export default function ErrorPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  return (
    <AuthLayout>
      {/* We use a manual card here because it's not an Ory component, 
          but we want it to look similar to Ory cards styled via CSS */}
      <div className="ory-elements">
        <div data-testid="ory/card" className="bg-background border border-border">
          <div className="text-center px-4 py-6">
            <h2 className="mb-4 text-xl font-bold">
              Authentication Error
            </h2>

            {error && (
              <div className="mb-4 rounded-md border p-4 bg-muted/50 text-left">
                <p className="font-semibold text-sm">
                  {error}
                </p>
                {errorDescription && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {errorDescription}
                  </p>
                )}
              </div>
            )}

            <p className="mb-8 text-sm text-muted-foreground">
              Something went wrong during authentication. Please try again.
            </p>

            <div className="space-y-3">
              <Button
                onClick={() => router.push("/auth/login")}
                className="w-full bg-[#2252b3] hover:bg-[#1a3f8a] text-white h-[40px] rounded-[4px]"
              >
                Try Again
              </Button>
              <Button
                onClick={() => router.push("/")}
                variant="outline"
                className="w-full h-[40px] rounded-[4px]"
              >
                Go Home
              </Button>
            </div>
          </div>
        </div>
      </div>
    </AuthLayout>
  );
}
