interface TaskInfoTabsProps {
  activeTab: "overview" | "model";
  setActiveTab: (tab: "overview" | "model") => void;
}

export default function TaskInfoTabs({ activeTab, setActiveTab }: TaskInfoTabsProps) {
  return (
    <div className="px-3 pt-2.5 pb-1.5 text-xs">
      <div className="relative flex w-full items-center gap-px rounded-md bg-sidebar p-0.5">
        {/* Animated active background */}
        <div
          className={`absolute inset-y-0 w-1/2 rounded-md bg-card shadow-sm ring-1 ring-border/60 transition-transform duration-200 ${
            activeTab === "overview" ? "translate-x-0" : "translate-x-full"
          }`}
        />
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`relative z-10 flex-1 rounded-md px-3 py-1.5 text-xs font-medium text-center transition-colors ${
            activeTab === "overview"
              ? "text-foreground"
              : "text-muted-foreground"
          }`}
        >
          Overview
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("model")}
          className={`relative z-10 flex-1 rounded-md px-3 py-1.5 text-xs font-medium text-center transition-colors ${
            activeTab === "model"
              ? "text-foreground"
              : "text-muted-foreground"
          }`}
        >
          Model info
        </button>
      </div>
    </div>
  );
}
