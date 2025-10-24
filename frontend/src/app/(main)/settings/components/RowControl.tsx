import { Label } from "@/components/ui/label";

type RowControlProps = {
  title: string;
  description: string;
  children: React.ReactNode;
};

export default function RowControl({
  title,
  description,
  children,
}: RowControlProps) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-primary/5 p-4 dark:bg-zinc-700/50">
      <div className="space-y-0.5">
        <Label className="text-base text-primary dark:text-zinc-200">
          {title}
        </Label>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </div>
  );
}
