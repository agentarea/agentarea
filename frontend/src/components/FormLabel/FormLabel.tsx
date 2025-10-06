import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";

type FormLabelProps = {
    icon?: LucideIcon;
    children: React.ReactNode;
    className?: string;
    required?: boolean;
    optional?: boolean;
    htmlFor?: string;
}

export default function FormLabel({ htmlFor, children, className, icon: IconComponent, required, optional, ...props }: FormLabelProps) {
    return (
        <Label htmlFor={htmlFor} className={cn("label", className)}>
            {IconComponent && (
                <div className="bg-gradient-to-br from-primary/10 to-[#966DFF]/10 rounded-sm p-1">
                    <IconComponent className="label-icon" style={{ strokeWidth: 1.5 }} />
                </div>
            )}
            {children} 
            {required && <span className="text-sm text-red-500">*</span>} 
            {optional && <span className="text-xs font-light text-zinc-400">(Optional)</span>}
        </Label>
  );
}