"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useRouter } from "next/navigation";

export default function SignOut() {
  const router = useRouter();

  const handleSignOut = () => {
    // Перенаправляем прямо на Ory Kratos logout flow
    window.location.href = `${process.env.NEXT_PUBLIC_ORY_SDK_URL}/self-service/logout/browser`;
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-purple-600 to-indigo-700 dark:from-gray-900 dark:via-gray-800 dark:to-slate-900">
      <Card className="w-full max-w-md p-8 bg-white/95 dark:bg-gray-800/95 shadow-2xl rounded-xl backdrop-blur-sm border border-white/20 dark:border-gray-700/20">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Sign out of AgentArea
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            Are you sure you want to sign out?
          </p>
        </div>

        <div className="flex flex-col gap-4">
          <Button
            type="button"
            variant="destructive"
            className="w-full"
            onClick={handleSignOut}
          >
            Sign Out
          </Button>

          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => router.push("/workplace")}
          >
            Cancel
          </Button>
        </div>
      </Card>
    </div>
  );
}