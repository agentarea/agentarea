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
        "text-xs flex items-center gap-1 p-1",
        "transition-all duration-300",
        className,
        isActive
          ? "bg-background text-primary bg-sidebar-accent rounded-sm"
          : "text-muted-foreground hover:text-foreground "
      )}
    >
      {children}
    </Link>
  );
}


