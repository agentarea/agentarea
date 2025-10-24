"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface Props {
  href: string;
  children: React.ReactNode;
  className?: string;
}

export default function ActiveLink({ href, children, className }: Props) {
  const pathname = usePathname();
  const isActive = pathname === href;

  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "flex items-center gap-1 p-1 text-xs",
        "transition-all duration-300",
        className,
        isActive
          ? "rounded-sm bg-background bg-sidebar-accent text-primary"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </Link>
  );
}
