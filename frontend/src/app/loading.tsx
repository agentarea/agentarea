import React from "react";

export default function Loading() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="flex flex-col items-center gap-4">
        <div className="h-16 w-16 border-t-4 border-primary rounded-full animate-spin"></div>
        <p className="text-lg font-medium text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}
