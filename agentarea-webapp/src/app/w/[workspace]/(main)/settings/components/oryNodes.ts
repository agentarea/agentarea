import type { UiNode, UiNodeGroupEnum, UiText } from "@ory/client-fetch";
import { isUiNodeInput } from "@ory/elements-react";

export const groupNodes = (nodes: UiNode[], group: UiNodeGroupEnum) =>
  nodes.filter((node) => node.group === group);

/** The fields a person edits: inputs that are neither hidden nor a submit. */
export const fieldNodes = (nodes: UiNode[]) =>
  nodes
    .filter(isUiNodeInput)
    .filter(
      ({ attributes }) =>
        attributes.type !== "hidden" && attributes.type !== "submit"
    );

/** Hidden inputs, such as the CSRF token every section form must carry. */
export const hiddenNodes = (nodes: UiNode[]) =>
  nodes
    .filter(isUiNodeInput)
    .filter(({ attributes }) => attributes.type === "hidden");

export const findInput = (nodes: UiNode[], name: string) =>
  nodes
    .filter(isUiNodeInput)
    .find(({ attributes }) => attributes.name === name);

export const errorsOf = (messages: UiText[] | undefined) =>
  (messages ?? []).filter((message) => message.type === "error");

/**
 * Kratos took the section's last submit: the flow it answered with is in the
 * success state and flags neither the flow nor the section's own nodes.
 */
export const submitAccepted = (
  flow: { state: unknown; ui: { messages?: UiText[] } },
  sectionNodes: UiNode[]
) =>
  flow.state === "success" &&
  errorsOf(flow.ui.messages).length === 0 &&
  sectionNodes.every((node) => errorsOf(node.messages).length === 0);

/**
 * The sign-in providers of the settings flow. Kratos offers one as a `link`
 * button while it is not connected and as an `unlink` button while it is; a
 * provider that is the account's only way to sign in gets no button at all,
 * so it cannot be listed. `label` is the name Kratos gives it: its `label` in
 * kratos.yml, else its id.
 */
export const socialProviders = (oidcNodes: UiNode[]) =>
  oidcNodes
    .filter(isUiNodeInput)
    .filter(({ attributes }) => ["link", "unlink"].includes(attributes.name))
    .map(({ attributes, meta }) => {
      const { provider } = (meta.label?.context ?? {}) as {
        provider?: unknown;
      };
      return {
        id: String(attributes.value),
        label:
          typeof provider === "string" ? provider : String(attributes.value),
        connected: attributes.name === "unlink",
      };
    });
