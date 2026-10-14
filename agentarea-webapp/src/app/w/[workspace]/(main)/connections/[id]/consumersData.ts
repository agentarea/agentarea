import { getTranslations } from "next-intl/server";
import { getMCPInstanceConsumers, type MCPInstanceConsumer } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";

export interface ConsumersResult {
  consumers: MCPInstanceConsumer[] | null;
  error: string | null;
}

/**
 * Which agents attach this connection. A failure is returned as a message for
 * the page to show, never as an empty list: "nobody uses it" would be a lie.
 */
export async function loadConsumers(instanceId: string): Promise<ConsumersResult> {
  const t = await getTranslations("MCPServersPage.instanceDetail.errors");
  try {
    const result = await getMCPInstanceConsumers(instanceId);
    return result.error || !result.data
      ? {
          consumers: null,
          error: apiErrorMessage(result, t("consumersLoadFailed")),
        }
      : { consumers: result.data, error: null };
  } catch (error) {
    return {
      consumers: null,
      error: `${t("consumersLoadFailed")}: ${formatApiError(error)}`,
    };
  }
}
