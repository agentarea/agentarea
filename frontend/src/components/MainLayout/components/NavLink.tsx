"use client"

import React, { forwardRef, ReactNode } from "react";
import Link from "next/link";
import { usePathname } from 'next/navigation';
import { cn } from "@/lib/utils";

export type NavLinkProps = {
    link: string;
    text: string;
    icon: ReactNode;
    disabled?: boolean;
};

const NavLink = forwardRef<HTMLAnchorElement, NavLinkProps>(
    ({ link, text, icon, disabled, ...props }, ref) => {
        const pathname = usePathname();
        const isActive = pathname === link;

        return (
            <Link
                ref={ref}
                href={link}
                className={cn(
                    disabled && "opacity-30 pointer-events-none",
                    isActive 
                        ? "pointer-events-none text-accent dark:text-primary-foreground bg-primary/20 dark:bg-white/70 dark:text-zinc-800" 
                        : "text-foreground hover:bg-zinc-200/60 hover:dark:bg-white/10",
                    "relative text-[14px] leading-[14px] flex flex-row gap-[8px] items-center",
                    "py-[10px] px-[10px] rounded-[8px]",
                    "group transition-colors duration-300"
                )}
                {...props}
            >
                {icon}
                
                <span className="">
                    {text}
                </span>
            </Link>
        );
    }
);

NavLink.displayName = "NavLink";
export default NavLink;