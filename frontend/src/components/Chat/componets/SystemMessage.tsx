import React from "react";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface SystemData {
  message: string;
  level?: "info" | "warning" | "error";
}

const SystemMessage: React.FC<{ data: SystemData }> = ({ data }) => {
  const levelColors = {
    info: "text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-300 dark:bg-blue-950/30 dark:border-blue-800",
    warning:
      "text-yellow-600 bg-yellow-50 border-yellow-200 dark:text-yellow-300 dark:bg-yellow-950/30 dark:border-yellow-800",
    error:
      "text-red-600 bg-red-50 border-red-200 dark:border-red-800 dark:text-red-300 dark:bg-red-950/30",
  };

  const levelClass = levelColors[data.level || "info"];

  return (
    <MessageWrapper type="info">
      <BaseMessage headerLeft={"System message"} headerRight={null}>
        <div className={`${levelClass}`}>{data.message}</div>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default SystemMessage;
