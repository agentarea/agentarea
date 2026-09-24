"use client";

import React from "react";
import { useTranslations } from "next-intl";
import BaseMessage from "@/components/Chat/componets/BaseMessage";
import LLMResponseMessage from "@/components/Chat/componets/LLMResponseMessage";
import MessageWrapper from "@/components/Chat/componets/MessageWrapper";
import { extractInboxResult, getInboxResultDetails } from "./inboxResult";

interface InboxResultMessageProps {
  id: string;
  agentId: string;
  result: unknown;
  agentName?: string | null;
  timestamp?: string | null;
}

/**
 * Assistant-style presentation for the final inbox result. Known response
 * envelopes become markdown content; unfamiliar objects stay accessible under
 * a deliberate structured-output disclosure.
 */
export function InboxResultMessage({
  id,
  agentId,
  result,
  agentName,
  timestamp,
}: InboxResultMessageProps) {
  const t = useTranslations("InboxPage.result");
  const view = extractInboxResult(result);
  if (view.kind === "empty") return null;
  const details = getInboxResultDetails(result);

  return (
    <>
      {view.kind === "text" ? (
        <LLMResponseMessage
          data={{
            id,
            timestamp: timestamp || "",
            agent_id: agentId,
            event_type: "llm.call.completed",
            content: view.content,
          }}
          agent_name={agentName || undefined}
        />
      ) : (
        <MessageWrapper>
          <BaseMessage
            headerLeft={agentName || t("assistant")}
            headerRight={timestamp || null}
          >
            <details>
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                {t("structured")}
              </summary>
              <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-2 font-mono text-xs [overflow-wrap:anywhere]">
                {view.content}
              </pre>
            </details>
          </BaseMessage>
        </MessageWrapper>
      )}
      {view.kind === "text" && details && (
        <details className="ml-11 mt-2 border-t border-border/60 pt-2">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
            {t("details")}
          </summary>
          <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-2 font-mono text-xs [overflow-wrap:anywhere]">
            {JSON.stringify(details, null, 2)}
          </pre>
        </details>
      )}
    </>
  );
}

export default InboxResultMessage;
