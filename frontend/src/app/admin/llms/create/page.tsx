import ContentBlock from "@/components/ContentBlock/ContentBlock";
import LLMModelForm from "./LLMModelForm";
import { listLLMModels } from "@/lib/api";
import { getTranslations } from "next-intl/server";
import { Card } from "@/components/ui/card";

export default async function AddLLMModelPage() {
  // TODO: Fetch default LLMs or other server data here if needed
  // For now, just render the form
  const llms = await listLLMModels();
  const t = await getTranslations('LlmBrowsePage.create');

  return (
    <ContentBlock
      header={{
        title: t('addNewLlm'),
        backLink: {
          label: t('backToLlmModels'),
          href: "/admin/llms"
        }
      }}
    >
    <Card className="max-w-2xl mx-auto">      
      {/* <div className="mb-6">
        <h1 className="text-2xl font-semibold">Add LLM Model</h1>
        <p className="note">
          Connect an LLM to use in your agents and tasks
        </p> 
      </div> */}
      <LLMModelForm llms={llms.data ?? []} />
    </Card>
    </ContentBlock>
  );
}
