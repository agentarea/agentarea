import { useCallback, useState } from "react";
import { setBoundValue } from "../utils/a2uiForm";

/**
 * Local, editable copy of a surface's data model. Resets when the agent sends
 * a new model; edits never write back into the surface the reducer holds.
 */
export function useA2UIDataModel(source: Record<string, unknown>) {
  const [local, setLocal] = useState({ source, model: source });
  if (local.source !== source) setLocal({ source, model: source });

  const setValue = useCallback(
    (path: string, value: unknown) =>
      setLocal((previous) => ({
        ...previous,
        model: setBoundValue(previous.model, path, value),
      })),
    []
  );

  return [local.model, setValue] as const;
}
