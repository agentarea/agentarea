import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type SettingsCardProps = {
    title: string;
    description: string;
    icon: React.ElementType;
    children: React.ReactNode;
}

export default function SettingsCard({ title, description, icon, children }: SettingsCardProps) {
    const Icon = icon;

    return (
        <Card className="card p-0 overflow-hidden card-shadow">
            <CardHeader className="px-6 py-4 border-b border-zinc-200/50 dark:border-zinc-700/50">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-lg bg-primary/5 dark:bg-zinc-700/50 shadow-sm">
                        <Icon className="w-5 h-5 text-primary/70 dark:text-zinc-400" />
                    </div>
                    <div>
                        <CardTitle className="text-lg">{title}</CardTitle>
                        <CardDescription className="text-sm">{description}</CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="pt-6 space-y-8">
                {children}
            </CardContent>
        </Card>
    )
}