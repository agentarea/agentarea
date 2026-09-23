import React from "react";
import A2UIMessage from "@/components/Chat/componets/A2UIMessage";
import type {
  A2UIActionHandler,
  A2UIComponent,
  A2UISurface,
} from "@/components/Chat/types";
import type { A2UISurfaceState } from "../a2ui";
import type { Part } from "../contract";

interface A2uiPartProps {
  part: Part;
  disabled?: boolean;
  onAction?: A2UIActionHandler;
}

/**
 * Renders an accumulated A2UI surface via the existing A2UIMessage renderer.
 * The reducer folds create/update-components/update-data events into a single
 * surface state on the part; delete removes the part entirely.
 */
export const A2uiPart: React.FC<A2uiPartProps> = ({
  part,
  onAction,
  disabled,
}) => {
  const state = part.data.surface as A2UISurfaceState | undefined;
  if (!state) return null;

  const surface: A2UISurface = {
    surfaceId: state.surface_id,
    catalogId: state.catalog_id,
    theme: state.theme,
    sendDataModel: state.send_data_model,
    components: state.components as Record<string, A2UIComponent>,
    dataModel: state.dataModel,
  };

  return (
    <A2UIMessage
      disabled={disabled}
      data={{
        id: state.surface_id,
        timestamp: "",
        agent_id: "",
        event_type: part.eventType,
        surfaceId: state.surface_id,
        surface,
      }}
      onAction={
        onAction
          ? (action, sourceId, context) =>
              onAction(action, state.surface_id, sourceId, context)
          : undefined
      }
    />
  );
};

export default A2uiPart;
