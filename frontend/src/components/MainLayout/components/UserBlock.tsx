"use client";

import { Button } from "@/components/ui/button";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { LogOut } from "lucide-react";
import { BottomNavContent } from "../MainLayout";
import { cn } from "@/lib/utils";
import { useUser, SignOutButton } from "@clerk/nextjs";

type UserBlockProps = {
    user?: BottomNavContent["user"];
    isCollapsed?: boolean;
};

export default function UserBlock({ user, isCollapsed }: UserBlockProps) {
    const { user: clerkUser, isLoaded } = useUser();

    // Use Clerk user data if available, otherwise fall back to props
    const displayUser = clerkUser ? {
        name: clerkUser.fullName || clerkUser.firstName || "User",
        email: clerkUser.emailAddresses[0]?.emailAddress || "",
        avatar: clerkUser.imageUrl || ""
    } : user || {
        name: "User",
        email: "",
        avatar: ""
    };

    if (!isLoaded) {
        return (
            <div className={cn(
                "flex items-center py-[4px] justify-between"
            )}>
                <div className={cn(
                    "flex items-center gap-[8px]",
                    isCollapsed && "flex-col"
                )}>
                    <Avatar className="h-[35px] w-[35px]">
                        <AvatarFallback>...</AvatarFallback>
                    </Avatar>
                    {!isCollapsed && (
                        <div className="flex flex-col">
                            <span className="text-[13px] font-medium overflow-hidden text-ellipsis whitespace-nowrap md:max-w-[102px]">
                                Loading...
                            </span>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className={cn(
            "flex items-center py-[4px] justify-between"
        )}>
            <div className={cn(
                "flex items-center gap-[8px]",
                isCollapsed && "flex-col"
            )}>
                <Avatar className="h-[35px] w-[35px]">
                    <AvatarImage src={displayUser.avatar} />
                    <AvatarFallback>
                        {displayUser.name.charAt(0)}
                    </AvatarFallback>
                </Avatar>
                {!isCollapsed && (
                    <div className="flex flex-col">
                        <span className="text-[13px] font-medium overflow-hidden text-ellipsis whitespace-nowrap md:max-w-[102px]">
                            {displayUser.name}
                        </span>
                        <span className="text-[12px] text-zinc-400 overflow-hidden text-ellipsis whitespace-nowrap md:max-w-[102px]">
                            {displayUser.email}
                        </span>
                    </div>
                )}
            </div>
            {!isCollapsed && clerkUser && (
                <div>
                    <SignOutButton>
                        <Button size="icon" variant="ghost" className="w-7 h-7">
                            <LogOut className="h-4 w-4" />
                        </Button>
                    </SignOutButton>
                </div>
            )}
        </div>
    );
}