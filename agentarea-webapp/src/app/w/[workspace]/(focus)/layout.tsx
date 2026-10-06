import { AuthLayout } from "@/components/auth/auth-layout";
import AuthGuard from "@/components/auth/AuthGuard";

/**
 * Pages opened from a link sent to a chat: one card with the one action the
 * link is for, without the app's sidebar. Session and membership are still
 * checked by the proxy and the workspace layout above.
 */
export default function FocusLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthLayout>
      <AuthGuard>{children}</AuthGuard>
    </AuthLayout>
  );
}
