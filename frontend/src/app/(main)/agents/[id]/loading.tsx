import React from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";

export default function Loading() {
  return (
    <div className="flex h-64 items-center justify-center">
      <LoadingSpinner />
    </div>
  );
}
