/**
 * Which egress exit a container connection leaves the internet through: the
 * exit's id under `json_spec.egress_exit`. Shared by the create form, the
 * connection page and its server action.
 */

import type { EgressExitResponse, McpTransport } from "@/api/client/types.gen";
import { editableInstanceSpec } from "./credential-fields";

export const EGRESS_EXIT_SPEC_KEY = "egress_exit";

/** An exit as the picker lists it. */
export interface EgressExitOption {
  id: string;
  name: string;
}

/** What the picker offers, or why the list did not load. */
export type EgressExitChoices =
  | { ok: true; exits: EgressExitOption[] }
  | { ok: false; message: string };

/** Only docker and command connections run a container to route. */
export function bindsEgressExit(transport: McpTransport): boolean {
  return transport === "docker" || transport === "command";
}

export function toEgressExitOptions(
  exits: EgressExitResponse[]
): EgressExitOption[] {
  return exits.map((exit) => ({ id: exit.id, name: exit.name }));
}

export function boundEgressExit(
  instanceJsonSpec: Record<string, unknown>
): string | null {
  const value = instanceJsonSpec[EGRESS_EXIT_SPEC_KEY];
  return typeof value === "string" && value ? value : null;
}

/** A new connection's spec, leaving through `exitId` or, with null, directly. */
export function withEgressExit(
  jsonSpec: Record<string, unknown>,
  exitId: string | null
): Record<string, unknown> {
  const spec = { ...jsonSpec };
  delete spec[EGRESS_EXIT_SPEC_KEY];
  if (exitId) spec[EGRESS_EXIT_SPEC_KEY] = exitId;
  return spec;
}

/** The instance update that binds `exitId`, or unbinds with null. */
export function egressExitUpdateSpec(
  instanceJsonSpec: Record<string, unknown>,
  exitId: string | null
): Record<string, unknown> {
  return withEgressExit(editableInstanceSpec(instanceJsonSpec), exitId);
}
