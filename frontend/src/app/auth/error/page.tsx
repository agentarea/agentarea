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
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-red-600 via-purple-600 to-indigo-700">
      <Card className="w-full max-w-md rounded-xl border border-white/20 bg-white/95 p-8 shadow-2xl backdrop-blur-sm dark:border-gray-700/20 dark:bg-gray-800/95">
        <div className="text-center">
          <h1 className="mb-4 text-2xl font-bold text-gray-900 dark:text-white">
            Authentication Error
          </h1>

          {error && (
            <div className="mb-4 rounded-md border border-red-300 bg-red-100 p-4 dark:border-red-700 dark:bg-red-900/20">
              <p className="font-medium text-red-800 dark:text-red-200">
                {error}
              </p>
              {errorDescription && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-300">
                  {errorDescription}
                </p>
              )}
            </div>
          )}

          <p className="mb-6 text-gray-600 dark:text-gray-400">
            Something went wrong during authentication. Please try again.
          </p>

          <div className="space-y-3">
            <Button
              onClick={() => router.push("/auth/login")}
              className="w-full bg-blue-600 hover:bg-blue-700"
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
