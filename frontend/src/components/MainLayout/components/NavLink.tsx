"use client"

import React, { forwardRef, ReactElement, cloneElement } from "react";
import Link from "next/link";
import { usePathname } from 'next/navigation';
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { LucideProps } from "lucide-react";
export type NavLinkProps = {
    link: string;
    text: string;
    icon?: ReactElement<LucideProps>;
    disabled?: boolean;
    isCollapsed?: boolean;
};

const NavLink = forwardRef<HTMLAnchorElement, NavLinkProps>(
    ({ link, text, icon, disabled, isCollapsed, ...props }, ref) => {
        const pathname = usePathname();
        const isActive = pathname === link;

        const iconToRender =  React.isValidElement(icon) ? cloneElement(icon, {
                className: cn(icon.props.className, "w-5 h-5"),
                strokeWidth: 1.5,
            }) : null;

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
                    "group transition-all duration-300 gap-[8px] font-light"
                )}
                tabIndex={0}
                aria-label={text}
                {...props}
            >
                {iconToRender && (
                    <div className="flex items-center justify-center"> {/* Wrapper for alignment only */}
                        {iconToRender}
                    </div>
                )}
                <span
                    className={cn(
                        "transition-all duration-300 whitespace-nowrap",
                        isCollapsed ? "w-0 opacity-0" : "opacity-100"
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