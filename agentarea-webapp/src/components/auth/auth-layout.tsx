import React from "react";

export const AuthLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="relative flex min-h-screen w-full flex-col sm:items-center sm:justify-center sm:px-4 sm:py-10">
      {/* Background with decorative lines */}
      <div className="pointer-events-none fixed inset-0 bg-background" />
      <div className="pointer-events-none fixed inset-0 bg-[url('/lines.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 dark:hidden" />
      <div className="pointer-events-none fixed inset-0 hidden bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-25 dark:block" />

      {/* Auth Card Container */}
      <div className="login-ory relative z-10 w-full max-w-md my-auto flex flex-col sm:h-auto">
        {children}
      </div>
    </div>
  );
};
