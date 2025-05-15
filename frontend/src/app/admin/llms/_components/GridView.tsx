// import { LLMModel } from "@/lib/api";
import type { components } from "@/api/schema";
type LLMModelInstance = components["schemas"]["LLMModelInstanceResponse"];

export default function GridView({ instances }: { instances: LLMModelInstance[] }) {
  if (!instances.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="text-2xl font-semibold mb-2">No LLM instances found</div>
        <div className="text-muted-foreground mb-4">Set up a new LLM to get started.</div>
        {/* The add button is in the parent, so no button here */}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-[12px]">
      {instances.map((item) => (
        <div key={item.id} className="card card-shadow group">
          <div className="flex flex-col gap-2">
            <div className="font-[500] text-[16px] font-montserrat">{item.name}</div>
            <div className="text-[14px] opacity-50 line-clamp-2 pt-[10px]">{item.description}</div>
            <div className="text-xs text-muted-foreground">Status: {item.status}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
