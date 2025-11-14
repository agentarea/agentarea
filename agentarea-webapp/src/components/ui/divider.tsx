import { cn } from "@/lib/utils";

export default function Divider({ className }: { className?: string }) {
  return (
    <div className={cn("my-5 h-[1px] w-full bg-slate-200 dark:bg-slate-500 relative", className)}>
      <div className="h-[6px] w-[6px] bg-white dark:bg-zinc-700 border border-slate-400 dark:border-slate-100 rounded-full absolute top-[-3px] right-0"/>
      <div className="h-[6px] w-[6px] bg-white dark:bg-zinc-700 border border-slate-400 dark:border-slate-100 rounded-full absolute top-[-3px] left-0"/>
    </div>
  );
}
