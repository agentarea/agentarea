interface OpenAPIOperation {
  operationId?: string;
  summary?: string;
  description?: string;
}

interface OpenAPISpec {
  openapi?: string;
  info?: { title?: string; description?: string; version?: string };
  servers?: Array<{ url?: string }>;
  paths?: Record<
    string,
    Record<string, OpenAPIOperation | undefined> | null | undefined
  >;
}

export interface PreviewTool {
  name: string;
  description: string;
}

export interface OpenAPIPreview {
  title: string | null;
  description: string | null;
  version: string | null;
  base_url: string | null;
  tools: PreviewTool[];
}

export function resolveOpenAPIServerUrl(
  serverUrl: string | undefined,
  sourceSpecUrl?: string
): string | null {
  if (!serverUrl) return null;
  if (!sourceSpecUrl) return serverUrl;
  try {
    return new URL(serverUrl, sourceSpecUrl).toString();
  } catch {
    return serverUrl;
  }
}

export function isAbsoluteBaseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function previewFromOpenAPISpec(
  spec: OpenAPISpec,
  sourceSpecUrl?: string
): OpenAPIPreview {
  const info = spec.info || {};
  const tools: PreviewTool[] = [];

  if (spec.openapi && String(spec.openapi).startsWith("3.")) {
    const methods = ["get", "post", "put", "patch", "delete", "head", "options"];
    for (const [path, pathItem] of Object.entries(spec.paths || {})) {
      if (!pathItem || typeof pathItem !== "object") continue;
      for (const method of methods) {
        const operation = pathItem[method];
        if (!operation) continue;
        tools.push({
          name:
            operation.operationId ||
            `${method}_${path.replace(/[{}]/g, "").split("/").filter(Boolean).join("_")}`,
          description: operation.summary || operation.description || "",
        });
      }
    }
  }

  return {
    title: info.title || null,
    description: info.description || null,
    version: info.version || null,
    base_url: resolveOpenAPIServerUrl(spec.servers?.[0]?.url, sourceSpecUrl),
    tools,
  };
}
