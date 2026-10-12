/**
 * Client for an MCP instance's storage API on the manager: one bearer token
 * scopes every call to this instance's objects, and every write carries exactly one
 * precondition (`If-Match` to update, `If-None-Match: *` to create).
 */

/** The instance's storage API: {MCP_MANAGER_URL}/mcp/{MCP_INSTANCE_ID}/storage. */
export const storageUrl = (managerUrl: string, instanceId: string) =>
  `${managerUrl.replace(/\/+$/, "")}/mcp/${encodeURIComponent(instanceId)}/storage`;

export type Precondition = { ifMatch: string } | { ifNoneMatch: "*" };

export type StoredObject = { bytes: Uint8Array<ArrayBuffer>; etag: string };

export type PutResult = { ok: true; etag: string } | { ok: false; status: 412 };

export class StorageError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "StorageError";
  }
}

export class StorageClient {
  readonly #base: string;
  readonly #token: string;

  constructor(baseUrl: string, token: string) {
    this.#base = baseUrl.replace(/\/+$/, "");
    this.#token = token;
  }

  #url(path: string): string {
    return `${this.#base}/objects/${path.split("/").map(encodeURIComponent).join("/")}`;
  }

  async #request(method: string, path: string, init: { headers?: Record<string, string>; body?: Uint8Array<ArrayBuffer> } = {}) {
    const response = await fetch(this.#url(path), {
      method,
      headers: { Authorization: `Bearer ${this.#token}`, ...init.headers },
      body: init.body,
    });
    if (response.status === 401 || response.status === 403) {
      throw new StorageError(`MCP storage refused the token (${response.status} on ${method} ${path})`, response.status);
    }
    return response;
  }

  static async #fail(method: string, path: string, response: Response): Promise<never> {
    const detail = (await response.text().catch(() => "")).trim();
    throw new StorageError(
      `MCP storage ${method} ${path} failed: ${response.status}${detail ? ` ${detail}` : ""}`,
      response.status,
    );
  }

  static #etag(method: string, path: string, response: Response): string {
    const etag = response.headers.get("ETag");
    if (!etag) throw new StorageError(`MCP storage ${method} ${path} returned no ETag`, response.status);
    return etag;
  }

  /** The object's current ETag, or null when it does not exist. */
  async head(path: string): Promise<string | null> {
    const response = await this.#request("HEAD", path);
    if (response.status === 404) return null;
    if (!response.ok) return StorageClient.#fail("HEAD", path, response);
    return StorageClient.#etag("HEAD", path, response);
  }

  async get(path: string): Promise<StoredObject | null> {
    const response = await this.#request("GET", path);
    if (response.status === 404) return null;
    if (!response.ok) return StorageClient.#fail("GET", path, response);
    const etag = StorageClient.#etag("GET", path, response);
    return { bytes: new Uint8Array(await response.arrayBuffer()), etag };
  }

  /** A failed precondition is an expected outcome (someone else wrote first); everything else that is not 2xx throws. */
  async put(path: string, bytes: Uint8Array<ArrayBuffer>, precondition: Precondition, contentType: string): Promise<PutResult> {
    const headers: Record<string, string> = { "Content-Type": contentType };
    if ("ifMatch" in precondition) headers["If-Match"] = precondition.ifMatch;
    else headers["If-None-Match"] = precondition.ifNoneMatch;
    const response = await this.#request("PUT", path, { headers, body: bytes });
    if (response.status === 412) return { ok: false, status: 412 };
    if (response.status === 428) {
      throw new StorageError(`MCP storage PUT ${path} was sent without a precondition (428)`, 428);
    }
    if (!response.ok) return StorageClient.#fail("PUT", path, response);
    return { ok: true, etag: StorageClient.#etag("PUT", path, response) };
  }
}
