import React from "react";
import Link from "next/link";
import { User } from "lucide-react";
import { AttachmentCard } from "@/components/ui/attachment-card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { formatTimestamp } from "../../../utils/dateUtils";
import { renderTextWithMentions } from "@/utils/mentions";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface UserMessageProps {
  id: string;
  content: string;
  timestamp: string;
  files?: File[];
}

export const UserMessage: React.FC<UserMessageProps> = ({
  id,
  content,
  timestamp,
  files,
}) => {
  const handleFileDownload = (file: File) => {
    const url = URL.createObjectURL(file);
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
      <BaseMessage
        isUser={true}
        headerLeft={"User"}
        headerRight={formatTimestamp(new Date().toISOString())}
      >
        <div className="space-y-3">
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
                      className="leading-[17px] inline-block bg-primary/10 dark:bg-accent/30 text-primary dark:text-accent px-1 rounded hover:bg-primary/20 dark:hover:bg-accent/50 transition-colors cursor-pointer"
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
      </BaseMessage>
    </MessageWrapper>
    // <div className="ml-10 py-5 text-lg font-medium">
    //   {content}
    // </div>
  );
};

export default UserMessage;
