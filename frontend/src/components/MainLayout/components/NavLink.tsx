"use client"

import React, { forwardRef, ReactNode } from "react";
import Link from "next/link";
import { usePathname } from 'next/navigation';
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export type NavLinkProps = {
    link: string;
    text: string;
    icon: ReactNode;
    disabled?: boolean;
    isCollapsed?: boolean;
};

const NavLink = forwardRef<HTMLAnchorElement, NavLinkProps>(
    ({ link, text, icon, disabled, isCollapsed, ...props }, ref) => {
        const pathname = usePathname();
        const isActive = pathname === link;

        const linkNode = (
            <Link
                ref={ref}
                href={link}
                className={cn(
                    disabled && "opacity-30 pointer-events-none",
                    isActive 
                        ? "pointer-events-none text-accent dark:text-primary-foreground bg-primary/20 dark:bg-white/70 dark:text-zinc-800" 
                        : "text-foreground hover:bg-zinc-200/60 hover:dark:bg-white/10",
                    "relative text-[14px] leading-[14px] flex flex-row items-center",
                    "py-[10px] px-[10px] rounded-[8px]",
                    "group transition-all duration-300 gap-[8px]",
                )}
                tabIndex={0}
                aria-label={text}
                {...props}
            >
                <div className="w-5 h-5 flex items-center justify-center">
                    {icon}
                </div>
                <span
                    className={cn(
                        "transition-all duration-500 whitespace-nowrap",
                        isCollapsed ? "w-0 opacity-0" : " opacity-100"
                    )}
                >
                    {text}
                </span>
            </Link>
        );

        if (isCollapsed) {
            return (
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger asChild>{linkNode}</TooltipTrigger>
                        <TooltipContent side="right" className="select-none">
                            {text}
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            );
        }
        return linkNode;
    }
);

NavLink.displayName = "NavLink";
export default NavLink;