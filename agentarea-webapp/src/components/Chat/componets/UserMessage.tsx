import React from "react";
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
                if (part.isMention) {
                  return (
                    <span
                      key={index}
                      className="inline-block bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 font-medium px-1.5 py-0.5 rounded"
                    >
                      {part.text}
                    </span>
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
