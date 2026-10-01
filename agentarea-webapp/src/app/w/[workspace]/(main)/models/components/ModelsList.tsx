import { useTranslations } from "next-intl";
import type { ModelKind } from "@/api/client/types.gen";
import ModelBadge from "@/components/ui/model-badge";
import { ModelKindBadge } from "@/components/ui/model-kind-badge";

export interface ModelEntry {
  provider_name?: string | null;
  provider_icon_url?: string | null;
  model_display_name?: string | null;
  display_name?: string | null;
  model_name?: string | null;
  name?: string | null;
  kind?: ModelKind | null;
  model_kind?: ModelKind | null;
}

export default function ModelsList({ models }: { models: ModelEntry[] }) {
  const t = useTranslations("Models");
  return (
    <div>
      {models && models.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {models.slice(0, 2).map((model, index) => (
            <span key={index} className="flex min-w-0 items-center gap-1">
              <ModelBadge
                size="sm"
                className={`overflow-hidden [&>span]:truncate ${
                  models.length === 1 ? "max-w-full" : "max-w-[110px]"
                }`}
                providerName={model.provider_name ?? undefined}
                iconUrl={model.provider_icon_url ?? undefined}
                modelDisplayName={
                  model.model_display_name ||
                  model.display_name ||
                  model.model_name ||
                  model.name ||
                  t("unknownModel")
                }
              />
              <ModelKindBadge kind={model.kind ?? model.model_kind} />
            </span>
          ))}
          {models.length > 2 && (
            <span className="ml-1 text-xs opacity-60">
              +{models.length - 2}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
