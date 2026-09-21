import React from "react";
import type {
  A2UIAction,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import type { Part } from "../contract";
import { A2uiPart } from "./A2uiPart";
import { ArtifactPart } from "./ArtifactPart";
import { FormPart } from "./FormPart";
import { TextPart } from "./TextPart";
import { ToolPart } from "./ToolPart";

interface PartRendererProps {
  part: Part;
  onToolInspect?: () => void;
  suppressUnavailableDetails?: boolean;
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
  onToolInspect,
  suppressUnavailableDetails,
  onFormSubmit,
  onA2UIAction,
}) => {
  switch (part.kind) {
    case "llm":
      return <TextPart part={part} />;
    case "tool":
      return (
        <ToolPart
          part={part}
          onInspect={onToolInspect}
          suppressUnavailableDetails={suppressUnavailableDetails}
        />
      );
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
