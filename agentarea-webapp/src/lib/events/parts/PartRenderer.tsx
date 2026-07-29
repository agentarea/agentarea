import React from "react";
import type { Part } from "../contract";
import { TextPart } from "./TextPart";
import { ToolPart } from "./ToolPart";
import { FormPart } from "./FormPart";
import { ArtifactPart } from "./ArtifactPart";
import { A2uiPart } from "./A2uiPart";
import type { A2UIAction, HumanInputSecretValue } from "@/components/Chat/types";

interface PartRendererProps {
  part: Part;
  onFormSubmit?: (
    inputRequestId: string,
    answers: Record<string, unknown>,
    secrets: Record<string, HumanInputSecretValue>
  ) => void;
  onA2UIAction?: (
    action: A2UIAction,
    surfaceId: string,
    sourceComponentId: string
  ) => void;
}

/** Dispatch a Part to its kind-specific renderer. */
export const PartRenderer: React.FC<PartRendererProps> = ({
  part,
  onFormSubmit,
  onA2UIAction,
}) => {
  switch (part.kind) {
    case "llm":
      return <TextPart part={part} />;
    case "tool":
      return <ToolPart part={part} />;
    case "form":
      return <FormPart part={part} onSubmit={onFormSubmit} />;
    case "artifact":
      return <ArtifactPart part={part} />;
    case "a2ui":
      return <A2uiPart part={part} onAction={onA2UIAction} />;
    default:
      return null;
  }
};

export default PartRenderer;
