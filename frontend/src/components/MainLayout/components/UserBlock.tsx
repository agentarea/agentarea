"use client";

import { Button } from "@/components/ui/button";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { LogOut } from "lucide-react";
import { BottomNavContent } from "../MainLayout";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

type UserBlockProps = {
    user?: BottomNavContent["user"];
    isCollapsed?: boolean;
};

export default function UserBlock({ user, isCollapsed }: UserBlockProps) {
    const { user: authUser, isLoaded, signOut } = useAuth();

    // Use auth user data if available, otherwise fall back to props
    const displayUser = authUser ? {
        name: authUser.fullName || authUser.firstName || "User",
        email: authUser.email || "",
        avatar: authUser.imageUrl || ""
    } : user || {
        name: "User",
        email: "",
        avatar: ""
    };

    const handleSignOut = async () => {
        await signOut();
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
                        <AvatarFallback>
                            <span className="text-[15px] font-semibold text-zinc-400">?</span>
                        </AvatarFallback>
                    </Avatar>
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
            {!isCollapsed && authUser && (
                <div>
                    <Button 
                        size="icon" 
                        variant="ghost" 
                        className="w-7 h-7"
                        onClick={handleSignOut}
                    >
                        <LogOut className="h-4 w-4" />
                    </Button>
                </div>
            )}
        </div>
    );
}