"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function ErrorPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Card className="w-full max-w-md rounded-xl p-8 shadow-2xl">
        <div className="text-center">
          <h1 className="mb-4 text-2xl font-bold">
            Authentication Error
          </h1>

          {error && (
            <div className="mb-4 rounded-md border p-4">
              <p className="font-medium">
                {error}
              </p>
              {errorDescription && (
                <p className="mt-2 text-sm">
                  {errorDescription}
                </p>
              )}
            </div>
          )}

          <p className="mb-6">
            Something went wrong during authentication. Please try again.
          </p>

          <div className="space-y-3">
            <Button
              onClick={() => router.push("/auth/login")}
              className="w-full"
            >
              Try Again
            </Button>
            <Button
              onClick={() => router.push("/")}
              variant="outline"
              className="w-full"
            >
              Go Home
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
