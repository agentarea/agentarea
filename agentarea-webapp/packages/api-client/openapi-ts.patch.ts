/**
 * Drop the `workspace` path parameter from every operation. The URL template
 * keeps `/v1/workspaces/{workspace}/...`; the client transport fills it (see
 * packages/api-client/src/workspace-url.ts), so callers never pass it and the
 * generated types and schemas stop asking for it.
 */
export function dropWorkspacePathParam(
  _method: string,
  _path: string,
  operation: { parameters?: unknown[] }
): void {
  operation.parameters = operation.parameters?.filter(
    (parameter) =>
      !(
        typeof parameter === "object" &&
        parameter !== null &&
        "in" in parameter &&
        parameter.in === "path" &&
        "name" in parameter &&
        parameter.name === "workspace"
      )
  );
}
