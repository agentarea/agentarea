export default function SectionTitle({children}: {children: React.ReactNode}) {
    return (
        <div className="whitespace-nowrap uppercase text-[10px] font-medium text-neutral-400 flex flex-row items-center gap-[6px]">
            {children}
            <div className="h-[1px] w-full bg-neutral-200/50 dark:bg-neutral-700" />
        </div>
    );
}