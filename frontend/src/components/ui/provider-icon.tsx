import React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

interface ProviderIconProps {
  iconUrl?: string | null;
  name: string;
  className?: string;
  size?: "sm" | "md" | "lg" | "xl";
}

const sizeClasses = {
  sm: "h-4 w-4",
  md: "h-6 w-6",
  lg: "h-8 w-8",
  xl: "h-12 w-12",
};

export function ProviderIcon({
  iconUrl,
  name,
  className,
  size = "md",
}: ProviderIconProps) {
  return (
    <Avatar className={cn(sizeClasses[size], className)}>
      {iconUrl && (
        <AvatarImage
          src={iconUrl}
          alt={`${name} icon`}
          className="object-contain p-0.5"
        />
      )}
      <AvatarFallback className="text-xs font-medium">
        {name.charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}
