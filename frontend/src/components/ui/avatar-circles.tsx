/* eslint-disable @next/next/no-img-element */
"use client";

import { cn } from "@/lib/utils";

interface Avatar {
  imageUrl: string;
//   profileUrl: string;
}
interface AvatarCirclesProps {
  className?: string;
//   numPeople?: number;
  maxDisplay: number;
  avatarUrls: Avatar[];
}

export const AvatarCircles = ({
//   numPeople,
  className,
  maxDisplay,
  avatarUrls,
}: AvatarCirclesProps) => {
  return (
    <div className={cn("z-10 flex -space-x-2 rtl:space-x-reverse", className)}>
      {avatarUrls.slice(0, maxDisplay).map((url, index) => (
        <div
          key={index}
        //   href={url.profileUrl}
        //   target="_blank"
          rel="noopener noreferrer"
        >
          <img
            key={index}
            className="h-8 w-8 rounded-full border-2 border-white dark:border-zinc-800 bg-white"
            src={url.imageUrl}
            width={40}
            height={40}
            alt={`Avatar ${index + 1}`}
          />
        </div>
      ))}
      {maxDisplay < avatarUrls.length && (
        <div
          className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-zinc-200 text-zinc-400 bg-white font-light text-center text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
        >
          +{avatarUrls.length - maxDisplay}
        </div>
      )}
    </div>
  );
};
