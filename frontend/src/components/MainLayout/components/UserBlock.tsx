import { Button } from "@/components/ui/button";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { LogOut } from "lucide-react";
import { BottomNavContent } from "../MainLayout";
import { cn } from "@/lib/utils";

type UserBlockProps = {
    user: BottomNavContent["user"];
    isCollapsed?: boolean;
};

export default function UserBlock({ user, isCollapsed }: UserBlockProps) {
    return (
        <div className={cn(
            "flex items-center py-[4px] justify-between"
        )}>
            <div className={cn(
                "flex items-center gap-[8px]",
                isCollapsed && "flex-col"
            )}>
                <Avatar className="h-[35px] w-[35px]">
                    <AvatarImage src={user.avatar} />
                    <AvatarFallback>
                        {user.name.charAt(0)}
                    </AvatarFallback>
                </Avatar>
                {!isCollapsed && (
                    <div className="flex flex-col">
                        <span className="text-[13px] font-medium overflow-hidden text-ellipsis whitespace-nowrap md:max-w-[102px]">
                            {user.name}
                        </span>
                        <span className="text-[12px] text-zinc-400 overflow-hidden text-ellipsis whitespace-nowrap md:max-w-[102px]">
                            {user.email}
                        </span>
                    </div>
                )}
            </div>
            {!isCollapsed && (
                <div>
                    <Button size="icon" variant="ghost" className="w-7 h-7">
                        <LogOut className="h-4 w-4" />
                    </Button>
                </div>
            )}
        </div>
    );
}