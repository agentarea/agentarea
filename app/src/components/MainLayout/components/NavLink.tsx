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
                        ? "pointer-events-none text-primary dark:text-primary-foreground bg-gradient-to-r from-primary/20 to-[#7f2fee4f] dark:from-primary dark:to-[#8f2fee]" 
                        : "text-foreground hover:bg-neutral-200/60 hover:dark:bg-white/10",
                    "relative text-[12px] leading-[14px] flex flex-row gap-[8px] items-center",
                    "py-[7px] px-[10px] rounded-[8px]",
                    "group"
                )}
                {...props}
            >
                <div className={cn(
                    isActive ? "text-primary dark:text-primary-foreground" : ""
                )}>
                    {icon}
                </div>
                
                <span className="transition-colors duration-200">
                    {text}
                </span>
            </Link>
        );
    }
);

NavLink.displayName = "NavLink";
export default NavLink;