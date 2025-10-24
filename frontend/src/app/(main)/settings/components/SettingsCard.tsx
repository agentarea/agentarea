import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type SettingsCardProps = {
  title: string;
  description: string;
  icon: React.ElementType;
  children: React.ReactNode;
};

export default function SettingsCard({
  title,
  description,
  icon,
  children,
}: SettingsCardProps) {
  const Icon = icon;

  return (
    <Card className="card card-shadow overflow-hidden p-0">
      <CardHeader className="border-b border-zinc-200/50 px-6 py-4 dark:border-zinc-700/50">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/5 p-2.5 shadow-sm dark:bg-zinc-700/50">
            <Icon className="h-5 w-5 text-primary/70 dark:text-zinc-400" />
          </div>
          <div>
            <CardTitle className="text-lg">{title}</CardTitle>
            <CardDescription className="text-sm">{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-8 pt-6">{children}</CardContent>
    </Card>
  );
}
