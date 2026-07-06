import type { BrowserContext, APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

export const apiBaseURL =
  process.env.PLAYWRIGHT_API_BASE_URL ?? process.env.API_URL ?? "http://localhost:8000";
export const kratosAdminURL =
  process.env.PLAYWRIGHT_KRATOS_ADMIN_URL ??
  process.env.ORY_ADMIN_URL ??
  "http://localhost:4434";
export const kratosPublicURL =
  process.env.PLAYWRIGHT_KRATOS_PUBLIC_URL ??
  process.env.ORY_SDK_URL ??
  "http://localhost:4433";
export const mailpitURL =
  process.env.PLAYWRIGHT_MAILPIT_URL ?? "http://localhost:8025";

export const testPassword = "Str0ng-Test-PW-xyz!";

export type AuthedUser = {
  identityId: string;
  email: string;
  jwt: string;
  sessionCookie: { name: string; value: string };
};

export function uniqueLabel(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function uniqueEmail(prefix: string) {
  return `${uniqueLabel(prefix)}@test.local`;
}

function parseSetCookie(header: string | null) {
  const cookies = new Map<string, string>();
  if (!header) {
    return cookies;
  }

  for (const part of header.split(/,(?=[^;]+?=)/)) {
    const [pair] = part.trim().split(";");
    const index = pair.indexOf("=");
    if (index > 0) {
      cookies.set(pair.slice(0, index), pair.slice(index + 1));
    }
  }
  return cookies;
}

async function readJson(response: Response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Expected JSON from ${response.url}, got ${response.status}: ${text}`);
  }
}

async function fetchJson(url: string, init?: RequestInit) {
  const response = await fetch(url, { redirect: "manual", ...init });
  const json = await readJson(response);
  return { response, json };
}

export async function createKratosUser(prefix: string): Promise<AuthedUser> {
  const email = uniqueEmail(prefix);
  const created = await fetchJson(`${kratosAdminURL}/admin/identities`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      schema_id: "default",
      traits: { email },
      credentials: { password: { config: { password: testPassword } } },
      verifiable_addresses: [
        {
          value: email,
          verified: true,
          via: "email",
          status: "completed",
        },
      ],
    }),
  });
  expect(created.response.status).toBe(201);
  const identityId = created.json.id as string;

  const flow = await fetchJson(`${kratosPublicURL}/self-service/login/browser`, {
    headers: { accept: "application/json" },
  });
  expect(flow.response.ok).toBeTruthy();
  const csrfToken = flow.json.ui.nodes.find(
    (node: any) => node.attributes?.name === "csrf_token"
  )?.attributes?.value;
  expect(csrfToken).toBeTruthy();
  const csrfCookie = parseSetCookie(flow.response.headers.get("set-cookie"));

  const body = new URLSearchParams({
    method: "password",
    identifier: email,
    password: testPassword,
    csrf_token: csrfToken,
  });
  const loginCookieHeader = Array.from(csrfCookie.entries())
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  const login = await fetchJson(flow.json.ui.action, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/x-www-form-urlencoded",
      cookie: loginCookieHeader,
    },
    body,
  });
  expect(login.response.ok).toBeTruthy();
  const loginCookies = parseSetCookie(login.response.headers.get("set-cookie"));
  const sessionCookieValue = loginCookies.get("ory_kratos_session");
  expect(sessionCookieValue).toBeTruthy();

  const allCookies = new Map([...csrfCookie, ...loginCookies]);
  const cookieHeader = Array.from(allCookies.entries())
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  const whoami = await fetchJson(
    `${kratosPublicURL}/sessions/whoami?tokenize_as=agentarea_jwt`,
    {
      headers: {
        accept: "application/json",
        cookie: cookieHeader,
      },
    }
  );
  expect(whoami.response.ok).toBeTruthy();
  expect(whoami.json.identity.id).toBe(identityId);

  return {
    identityId,
    email,
    jwt: whoami.json.tokenized,
    sessionCookie: { name: "ory_kratos_session", value: sessionCookieValue ?? "" },
  };
}

export async function deleteKratosUser(identityId: string) {
  await fetch(`${kratosAdminURL}/admin/identities/${identityId}`, {
    method: "DELETE",
  }).catch(() => undefined);
}

export async function installBrowserSession(
  context: BrowserContext,
  user: AuthedUser
) {
  await context.addCookies([
    {
      name: user.sessionCookie.name,
      value: user.sessionCookie.value,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
      expires: Math.floor(Date.now() / 1000) + 24 * 60 * 60,
    },
  ]);
}

export async function authedRequest(
  request: APIRequestContext,
  user: AuthedUser,
  method: "get" | "post" | "put" | "patch" | "delete",
  path: string,
  options: Record<string, unknown> = {}
) {
  return request[method](`${apiBaseURL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${user.jwt}`,
      ...((options.headers as Record<string, string> | undefined) ?? {}),
    },
  });
}

export async function authedFetch(
  request: APIRequestContext,
  user: AuthedUser,
  method: string,
  path: string,
  options: Record<string, unknown> = {}
) {
  return request.fetch(`${apiBaseURL}${path}`, {
    ...options,
    method,
    headers: {
      Authorization: `Bearer ${user.jwt}`,
      ...((options.headers as Record<string, string> | undefined) ?? {}),
    },
  });
}

export async function responseBody(response: { text(): Promise<string> }) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function registerUserThroughKratos(prefix: string) {
  const email = uniqueEmail(prefix);
  const flow = await fetchJson(`${kratosPublicURL}/self-service/registration/api`, {
    headers: { accept: "application/json" },
  });
  expect(flow.response.ok).toBeTruthy();

  const registration = await fetchJson(
    `${kratosPublicURL}/self-service/registration?flow=${flow.json.id}`,
    {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        method: "password",
        traits: { email },
        password: testPassword,
      }),
    }
  );
  expect(registration.response.ok).toBeTruthy();
  return { email, identityId: registration.json.identity.id as string };
}

export async function waitForMailpitMessage(
  email: string,
  subjectPattern: RegExp,
  timeoutMs = 15_000
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await fetch(`${mailpitURL}/api/v1/messages`);
    expect(response.ok).toBeTruthy();
    const payload = await response.json();
    const message = (payload.messages ?? []).find((item: any) => {
      const recipients = item.To ?? [];
      return (
        recipients.some((to: any) => to.Address === email) &&
        subjectPattern.test(item.Subject ?? "")
      );
    });
    if (message) {
      return message;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${email} mail in Mailpit`);
}
