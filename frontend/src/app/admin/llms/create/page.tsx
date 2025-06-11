import ContentBlock from "@/components/ContentBlock/ContentBlock";
import LLMModelForm from "./LLMModelForm";
import { listLLMModels } from "@/lib/api";

export default async function AddLLMModelPage() {
  // TODO: Fetch default LLMs or other server data here if needed
  // For now, just render the form
  const llms = await listLLMModels();

  return (
    <ContentBlock
      header={{
        title: "Add LLM Model",
        backLink: {
          label: "Back to LLM Models",
          href: "/admin/llms"
        }
      }}
    >
    <div className="max-w-2xl mx-auto">      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Add LLM Model</h1>
        <p className="text-muted-foreground">
          Connect an LLM to use in your agents and tasks
        </p>
      </div>
      <LLMModelForm llms={llms.data ?? []} />
    </div>
    </ContentBlock>
  );
}
