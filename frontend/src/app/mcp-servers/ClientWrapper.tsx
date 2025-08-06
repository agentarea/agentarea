"use client";

import AuthGuard from "@/components/auth/AuthGuard";

interface ClientWrapperProps {
  children: React.ReactNode;
}

export default function ClientWrapper({ children }: ClientWrapperProps) {
  return (
    <AuthGuard>
      {children}
    </AuthGuard>
  );
}