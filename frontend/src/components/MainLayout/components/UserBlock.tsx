import { Button } from "@/components/ui/button";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { LogOut } from "lucide-react";
import { BottomNavContent } from "../MainLayout";

export default function UserBlock({ user }: { user: BottomNavContent["user"] }) {
    return (
        <div className="flex items-center justify-between py-[4px]">
            <div className="flex items-center gap-[8px]">
                <Avatar className="h-[38px] w-[38px]">
                    <AvatarImage src={user.avatar} />
                    <AvatarFallback>
                        {user.name.charAt(0)}
                    </AvatarFallback>
                </Avatar>
                <div className="flex flex-col">
                    <span className="text-[14px] font-medium tex">
                        {user.name}
                    </span>
                    <span className="text-[12px] text-neutral-400">
                        {user.email}
                    </span>
                </div>
            </div>
            <div>
                <Button size="icon" variant="ghost">
                    <LogOut className="h-4 w-4" />
                </Button>
            </div>
        </div>
    )
}