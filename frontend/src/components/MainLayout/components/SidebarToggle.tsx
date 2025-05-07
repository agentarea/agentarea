import { ChevronLeft, ChevronRight } from 'lucide-react';

type SidebarToggleProps = {
    isCollapsed: boolean;
    onToggle: () => void;
};

export default function SidebarToggle({ isCollapsed, onToggle }: SidebarToggleProps) {
    return (
        <button
            onClick={onToggle}
            className="
                absolute -right-3 top-6
                w-6 h-6
                flex items-center justify-center
                rounded-full
                bg-white dark:bg-zinc-800
                border border-zinc-200 dark:border-zinc-700
                shadow-sm
                hover:bg-zinc-50 dark:hover:bg-zinc-700
                transition-colors
            "
        >
            {isCollapsed ? (
                <ChevronRight className="w-4 h-4 text-zinc-600 dark:text-zinc-400" />
            ) : (
                <ChevronLeft className="w-4 h-4 text-zinc-600 dark:text-zinc-400" />
            )}
        </button>
    );
} 