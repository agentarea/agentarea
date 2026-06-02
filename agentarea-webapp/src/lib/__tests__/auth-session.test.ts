/**
 * Tests for isProtectedRoute and hasLiveSession (pure functions).
 * Run with: npx tsx src/lib/__tests__/auth-session.test.ts
 */
import { isProtectedRoute, hasLiveSession } from "../auth-session";

let failed = 0;
function assertEqual<T>(actual: T, expected: T, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    failed += 1;
    console.error(
      `FAIL ${name}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`,
    );
  } else {
    console.log(`PASS ${name}`);
  }
}

// --- isProtectedRoute ---
assertEqual(isProtectedRoute("/agents"), true, "/agents → true");
assertEqual(isProtectedRoute("/agents/123"), true, "/agents/123 → true");
assertEqual(isProtectedRoute("/"), false, "/ → false");
assertEqual(isProtectedRoute("/auth/login"), false, "/auth/login → false");
// startsWith semantics: "/agentsfoo" matches the "/agents" prefix, matching
// the original PROTECTED_ROUTES.some(r => pathname.startsWith(r)) behavior.
assertEqual(isProtectedRoute("/agentsfoo"), true, "/agentsfoo → true (startsWith semantics)");
assertEqual(isProtectedRoute("/settings/profile"), true, "/settings/profile → true");

// --- hasLiveSession ---
const ORY = "http://ory.internal";

function mockFetch(
  result: { ok: boolean; status: number; json: () => Promise<unknown> } | Error,
  calls: { count: number },
): typeof fetch {
  return (async () => {
    calls.count += 1;
    if (result instanceof Error) {
      throw result;
    }
    return result as unknown as Response;
  }) as unknown as typeof fetch;
}

async function run() {
  // cookie null → false, and fetch NOT called
  {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({ tokenized: "jwt" }) },
      calls,
    );
    const res = await hasLiveSession(null, { orySdkUrl: ORY, fetchImpl });
    assertEqual(res, false, "cookie null → false");
    assertEqual(calls.count, 0, "cookie null → fetch NOT called");
  }

  // 200 + { tokenized: "jwt" } → true
  {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({ tokenized: "jwt" }) },
      calls,
    );
    const res = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    assertEqual(res, true, "200 + tokenized → true");
  }

  // 200 + {} (no tokenized) → false
  {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: true, status: 200, json: async () => ({}) },
      calls,
    );
    const res = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    assertEqual(res, false, "200 + no tokenized → false");
  }

  // 401 response → false
  {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(
      { ok: false, status: 401, json: async () => ({}) },
      calls,
    );
    const res = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    assertEqual(res, false, "401 → false");
  }

  // fetchImpl throws → false
  {
    const calls = { count: 0 };
    const fetchImpl = mockFetch(new Error("network down"), calls);
    const res = await hasLiveSession("ory_kratos_session=abc", {
      orySdkUrl: ORY,
      fetchImpl,
    });
    assertEqual(res, false, "fetch throws → false");
  }

  if (failed > 0) {
    console.error(`\n${failed} test(s) failed`);
    process.exit(1);
  } else {
    console.log("\nAll tests passed");
  }
}

run();
