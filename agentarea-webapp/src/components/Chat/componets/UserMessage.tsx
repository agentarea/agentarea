import React from "react";
import Link from "@/components/WorkspaceLink";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { renderTextWithMentions } from "@/utils/mentions";
import { useFormatTimestamp } from "../../../utils/dateUtils";
import MessageWrapper from "./MessageWrapper";

interface UserMessageProps {
  id: string;
  content: string;
  timestamp: string;
  files?: File[];
}

export const UserMessage: React.FC<UserMessageProps> = ({
  id: _id,
  content,
  timestamp,
  files,
}) => {
  const formatTimestamp = useFormatTimestamp();
  const handleFileDownload = (file: File) => {
    const url = URL.createObjectURL(
      new Blob([file], { type: "application/octet-stream" })
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <MessageWrapper type="user">
      <div className="min-w-0 max-w-[calc(100%-2.125rem)] sm:max-w-[76%]">
        <div className="mb-1 flex items-center justify-end gap-2 px-1 text-[11px] leading-4 text-muted-foreground">
          <span>User</span>
          {timestamp && <span>{formatTimestamp(timestamp)}</span>}
        </div>
        <div className="rounded-xl border border-border/40 bg-muted/70 px-4 py-2.5 text-[15px] leading-6 text-foreground/85 sm:text-[13px] sm:leading-[21px]">
          {content && (
            <div className="whitespace-pre-wrap break-words">
              {renderTextWithMentions(content).map((part, index) => {
                if (part.isMention && part.agentId) {
                  return (
                    <Link
                      key={index}
                      href={`/agents/${part.agentId}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-block rounded bg-foreground/5 px-1 leading-[17px] text-foreground underline decoration-border underline-offset-2 hover:bg-foreground/10"
                    >
                      {part.text}
                    </Link>
                  );
                }
                return <span key={index}>{part.text}</span>;
              })}
            </div>
          )}
          {files && files.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-3">
              {files.map((file, index) => (
                <AttachmentCard
                  key={index}
                  file={file}
                  onAction={() => handleFileDownload(file)}
                  actionType="download"
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </MessageWrapper>
  );
};

export default UserMessage;
