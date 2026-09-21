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

/**
 * An LLM provider's own mark, on a plate.
 *
 * The plate is the point: a bare logo on the page ground has nothing seating it
 * and reads as floating, and a black-on-transparent mark disappears outright in
 * dark mode. It stays light in both themes — see `.avatar-plate`. It is
 * deliberately not hued: a brand identifies itself, so the tile is only a
 * surface for it to sit on.
 *
 * Still a Radix Avatar rather than a plain `<img>` so a 404 on a registry icon
 * URL falls back to the initial instead of leaving a hole.
 */
export function ProviderIcon({
  iconUrl,
  name,
  className,
  size = "md",
}: ProviderIconProps) {
  return (
    <Avatar
      className={cn("avatar-plate rounded-[26%]", sizeClasses[size], className)}
    >
      {iconUrl && (
        <AvatarImage
          src={iconUrl}
          alt={`${name} icon`}
          className="object-contain p-[16%]"
        />
      )}
      <AvatarFallback className="rounded-[26%] bg-transparent text-[0.6em] font-semibold text-zinc-600">
        {name.charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}
