import React from "react";
import { useTranslations } from "next-intl";
import { UserMessage } from "@/components/Chat/componets/UserMessage";
import type { Part } from "../contract";

/** A person's message that entered the run: a follow-up, a queued message. */
export const MessagePart: React.FC<{ part: Part }> = ({ part }) => {
  const t = useTranslations("Chat.conversation");
  const content =
    typeof part.data.content === "string" && part.data.content
      ? part.data.content
      : part.data.content_stored_separately === true
        ? t("messageStoredSeparately")
        : "";
  const timestamp =
    typeof part.data.timestamp === "string" ? part.data.timestamp : "";

  return (
    <UserMessage id={part.partId} content={content} timestamp={timestamp} />
  );
};

export default MessagePart;
