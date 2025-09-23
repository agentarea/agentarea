"use client";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useRouter, useSearchParams } from "next/navigation";

export default function ErrorPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-600 via-purple-600 to-indigo-700">
      <Card className="w-full max-w-md p-8 bg-white/95 dark:bg-gray-800/95 shadow-2xl rounded-xl backdrop-blur-sm border border-white/20 dark:border-gray-700/20">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
            Authentication Error
          </h1>

          {error && (
            <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-md">
              <p className="text-red-800 dark:text-red-200 font-medium">
                {error}
              </p>
              {errorDescription && (
                <p className="text-red-600 dark:text-red-300 text-sm mt-2">
                  {errorDescription}
                </p>
              )}
            </div>
          )}

          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Something went wrong during authentication. Please try again.
          </p>

          <div className="space-y-3">
            <Button
              onClick={() => router.push("/auth/signin")}
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