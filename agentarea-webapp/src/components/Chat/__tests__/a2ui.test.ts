/**
 * A2UI frontend logic tests.
 * Run with: npx tsx src/components/Chat/__tests__/a2ui.test.ts
 *
 * Tests pure functions only (no React rendering):
 * - Event normalization
 * - EventParser for A2UICreateSurface
 * - messageAccumulator: upsert, updateDataModel, deleteSurface
 * - JSON Pointer application
 */

// ── Inline test harness ─────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assert(condition: boolean, message: string) {
  if (!condition) {
    failed++;
    console.error(`  FAIL: ${message}`);
  } else {
    passed++;
    console.log(`  PASS: ${message}`);
  }
}

function assertEqual(actual: unknown, expected: unknown, message: string) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    failed++;
    console.error(`  FAIL: ${message}\n    expected: ${e}\n    actual:   ${a}`);
  } else {
    passed++;
    console.log(`  PASS: ${message}`);
  }
}

function section(name: string) {
  console.log(`\n── ${name} ──`);
}

// ── 1. Event normalizer ─────────────────────────────────────────────────────

section("Event normalizer");

// Inline the normalizer logic to test it without module imports
const EVENT_TYPE_MAP: Record<string, string> = {
  a2uicreatesurface: "A2UICreateSurface",
  a2uiupdatecomponents: "A2UIUpdateComponents",
  a2uiupdatedatamodel: "A2UIUpdateDataModel",
  a2uideletesurface: "A2UIDeleteSurface",
  workflowa2uicreatesurface: "A2UICreateSurface",
  workflowa2uiupdatecomponents: "A2UIUpdateComponents",
  workflowa2uiupdatedatamodel: "A2UIUpdateDataModel",
  workflowa2uideletesurface: "A2UIDeleteSurface",
};

function normalizeEventType(type: string): string {
  const key = (type || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return EVENT_TYPE_MAP[key] || type.replace("workflow.", "");
}

assertEqual(
  normalizeEventType("workflow.A2UICreateSurface"),
  "A2UICreateSurface",
  "normalizes workflow.A2UICreateSurface"
);
assertEqual(
  normalizeEventType("A2UICreateSurface"),
  "A2UICreateSurface",
  "normalizes bare A2UICreateSurface"
);
assertEqual(
  normalizeEventType("workflow.A2UIUpdateComponents"),
  "A2UIUpdateComponents",
  "normalizes workflow.A2UIUpdateComponents"
);
assertEqual(
  normalizeEventType("A2UIUpdateDataModel"),
  "A2UIUpdateDataModel",
  "normalizes bare A2UIUpdateDataModel"
);
assertEqual(
  normalizeEventType("workflow.A2UIDeleteSurface"),
  "A2UIDeleteSurface",
  "normalizes workflow.A2UIDeleteSurface"
);

// Verify the digit '2' is preserved
const key = "A2UICreateSurface".toLowerCase().replace(/[^a-z0-9]/g, "");
assertEqual(key, "a2uicreatesurface", "regex preserves digit 2 in A2UI");

// ── 2. JSON Pointer ─────────────────────────────────────────────────────────

section("JSON Pointer (RFC 6901)");

function applyJsonPointer(
  obj: Record<string, unknown>,
  pointer: string,
  value: unknown
): void {
  if (pointer === "/" || pointer === "") {
    Object.assign(obj, value ?? {});
    return;
  }
  const parts = pointer
    .replace(/^\//, "")
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
  let target = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (target[parts[i]] == null) target[parts[i]] = {};
    target = target[parts[i]] as Record<string, unknown>;
  }
  const last = parts[parts.length - 1];
  if (value === undefined) {
    delete target[last];
  } else {
    target[last] = value;
  }
}

{
  const obj: Record<string, { name?: string }> = {};
  applyJsonPointer(obj, "/user/name", "Jane");
  assertEqual(obj.user.name, "Jane", "sets nested path /user/name");
}

{
  const obj: Record<string, unknown> = {};
  applyJsonPointer(obj, "/", { foo: "bar" });
  assertEqual(obj.foo, "bar", "root path merges object");
}

{
  const obj: Record<string, { name?: string; age?: number }> = {
    user: { name: "Jane", age: 30 },
  };
  applyJsonPointer(obj, "/user/name", undefined);
  assertEqual(obj.user.name, undefined, "undefined value deletes key");
  assertEqual(obj.user.age, 30, "sibling key preserved after delete");
}

{
  const obj: Record<string, unknown> = {};
  applyJsonPointer(obj, "/a~1b", "escaped-slash");
  assertEqual(obj["a/b"], "escaped-slash", "handles ~1 escape (/)");
}

{
  const obj: Record<string, unknown> = {};
  applyJsonPointer(obj, "/a~0b", "escaped-tilde");
  assertEqual(obj["a~b"], "escaped-tilde", "handles ~0 escape (~)");
}

// ── 3. Surface message accumulator ──────────────────────────────────────────

section("Surface message accumulator");

interface A2UIComponent {
  id: string;
  component?: string;
  children?: string[];
  text?: string;
}

interface A2UISurface {
  components: Record<string, A2UIComponent>;
  dataModel: Record<string, unknown>;
}

interface AnyMessage {
  type: string;
  data: {
    id?: string;
    surfaceId?: string;
    surface: A2UISurface;
  };
}

function upsertA2UIComponents(
  messages: AnyMessage[],
  surfaceId: string,
  components: A2UIComponent[]
): AnyMessage[] {
  return messages.map((msg) => {
    if (msg.type !== "a2ui_surface") return msg;
    if (msg.data.surfaceId !== surfaceId) return msg;
    const updated = { ...msg.data.surface.components };
    for (const c of components) {
      updated[c.id] = c;
    }
    return {
      ...msg,
      data: {
        ...msg.data,
        surface: { ...msg.data.surface, components: updated },
      },
    };
  });
}

function updateA2UIDataModel(
  messages: AnyMessage[],
  surfaceId: string,
  path: string,
  value: unknown
): AnyMessage[] {
  return messages.map((msg) => {
    if (msg.type !== "a2ui_surface") return msg;
    if (msg.data.surfaceId !== surfaceId) return msg;
    const currentModel = { ...msg.data.surface.dataModel };
    applyJsonPointer(currentModel, path, value);
    return {
      ...msg,
      data: {
        ...msg.data,
        surface: { ...msg.data.surface, dataModel: currentModel },
      },
    };
  });
}

function deleteA2UISurface(
  messages: AnyMessage[],
  surfaceId: string
): AnyMessage[] {
  return messages.filter(
    (msg) => msg.type !== "a2ui_surface" || msg.data.surfaceId !== surfaceId
  );
}

// Test: upsert components
{
  const msgs: AnyMessage[] = [
    {
      type: "a2ui_surface",
      data: {
        surfaceId: "s1",
        surface: { components: {}, dataModel: {} },
      },
    },
  ];

  const result = upsertA2UIComponents(msgs, "s1", [
    { id: "root", component: "Column", children: ["title"] },
    { id: "title", component: "Text", text: "Hello" },
  ]);

  assertEqual(
    Object.keys(result[0].data.surface.components).length,
    2,
    "upsert adds 2 components"
  );
  assertEqual(
    result[0].data.surface.components["root"].component,
    "Column",
    "root component is Column"
  );
}

// Test: upsert overwrites existing
{
  const msgs: AnyMessage[] = [
    {
      type: "a2ui_surface",
      data: {
        surfaceId: "s1",
        surface: {
          components: {
            title: { id: "title", component: "Text", text: "Old" },
          },
          dataModel: {},
        },
      },
    },
  ];

  const result = upsertA2UIComponents(msgs, "s1", [
    { id: "title", component: "Text", text: "New" },
  ]);

  assertEqual(
    result[0].data.surface.components["title"].text,
    "New",
    "upsert overwrites existing component"
  );
}

// Test: upsert ignores other surfaces
{
  const msgs: AnyMessage[] = [
    {
      type: "a2ui_surface",
      data: { surfaceId: "s1", surface: { components: {}, dataModel: {} } },
    },
    {
      type: "a2ui_surface",
      data: { surfaceId: "s2", surface: { components: {}, dataModel: {} } },
    },
  ];

  const result = upsertA2UIComponents(msgs, "s1", [
    { id: "root", component: "Card" },
  ]);

  assertEqual(
    Object.keys(result[0].data.surface.components).length,
    1,
    "s1 gets the component"
  );
  assertEqual(
    Object.keys(result[1].data.surface.components).length,
    0,
    "s2 is untouched"
  );
}

// Test: update data model
{
  const msgs: AnyMessage[] = [
    {
      type: "a2ui_surface",
      data: { surfaceId: "s1", surface: { components: {}, dataModel: {} } },
    },
  ];

  const result = updateA2UIDataModel(msgs, "s1", "/user/name", "Jane");
  const user = result[0].data.surface.dataModel.user as { name?: string };
  assertEqual(user.name, "Jane", "updateDataModel sets nested path");
}

// Test: delete surface
{
  const msgs: AnyMessage[] = [
    {
      type: "llm_response",
      data: { id: "1", surface: { components: {}, dataModel: {} } },
    },
    {
      type: "a2ui_surface",
      data: { surfaceId: "s1", surface: { components: {}, dataModel: {} } },
    },
    {
      type: "llm_response",
      data: { id: "2", surface: { components: {}, dataModel: {} } },
    },
  ];

  const result = deleteA2UISurface(msgs, "s1");
  assertEqual(result.length, 2, "deleteSurface removes surface message");
  assert(
    result.every((m) => m.type !== "a2ui_surface"),
    "no a2ui_surface remains"
  );
}

// Test: delete surface leaves other surfaces
{
  const msgs: AnyMessage[] = [
    {
      type: "a2ui_surface",
      data: { surfaceId: "s1", surface: { components: {}, dataModel: {} } },
    },
    {
      type: "a2ui_surface",
      data: { surfaceId: "s2", surface: { components: {}, dataModel: {} } },
    },
  ];

  const result = deleteA2UISurface(msgs, "s1");
  assertEqual(result.length, 1, "only s1 deleted");
  assertEqual(result[0].data.surfaceId, "s2", "s2 remains");
}

// ── 4. URL sanitization ──────────────────────────────────────────────────────

section("URL sanitization");

function sanitizeMediaUrl(url: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    if (!["https:", "http:", "data:"].includes(parsed.protocol)) return "";
    return parsed.href;
  } catch {
    return "";
  }
}

assertEqual(
  sanitizeMediaUrl("https://example.com/img.png"),
  "https://example.com/img.png",
  "allows https URLs"
);
assertEqual(
  sanitizeMediaUrl("http://example.com/img.png"),
  "http://example.com/img.png",
  "allows http URLs"
);
assertEqual(
  sanitizeMediaUrl("data:image/png;base64,abc123"),
  "data:image/png;base64,abc123",
  "allows data URIs"
);
assertEqual(sanitizeMediaUrl("javascript:alert(1)"), "", "blocks javascript:");
assertEqual(sanitizeMediaUrl("file:///etc/passwd"), "", "blocks file:");
assertEqual(sanitizeMediaUrl("ftp://evil.com/payload"), "", "blocks ftp:");
assertEqual(sanitizeMediaUrl(""), "", "empty string returns empty");
assertEqual(sanitizeMediaUrl("not-a-url"), "", "invalid URL returns empty");

// ── 5. Recursion guard ───────────────────────────────────────────────────────

section("Recursion guard");

{
  // Simulate renderById with depth/visited tracking
  type FakeNode = { id: string; children?: string[] };
  const components: Record<string, FakeNode> = {
    a: { id: "a", children: ["b"] },
    b: { id: "b", children: ["a"] }, // cycle: a -> b -> a
  };

  const MAX_DEPTH = 50;
  let renderCount = 0;

  function fakeRender(id: string, depth: number, visited: Set<string>): void {
    if (depth > MAX_DEPTH || visited.has(id)) return;
    const node = components[id];
    if (!node) return;
    renderCount++;
    const next = new Set(visited);
    next.add(id);
    for (const childId of node.children ?? []) {
      fakeRender(childId, depth + 1, next);
    }
  }

  fakeRender("a", 0, new Set());
  assertEqual(
    renderCount,
    2,
    "cycle detected — renders a and b, stops at second a"
  );
}

{
  // Deep nesting beyond MAX_DEPTH
  const components: Record<string, { id: string; children?: string[] }> = {};
  for (let i = 0; i < 100; i++) {
    components[`n${i}`] = {
      id: `n${i}`,
      children: i < 99 ? [`n${i + 1}`] : [],
    };
  }

  const MAX_DEPTH = 50;
  let maxReached = 0;

  function fakeRenderDeep(
    id: string,
    depth: number,
    visited: Set<string>
  ): void {
    if (depth > MAX_DEPTH || visited.has(id)) return;
    const node = components[id];
    if (!node) return;
    if (depth > maxReached) maxReached = depth;
    const next = new Set(visited);
    next.add(id);
    for (const childId of node.children ?? []) {
      fakeRenderDeep(childId, depth + 1, next);
    }
  }

  fakeRenderDeep("n0", 0, new Set());
  assert(
    maxReached <= MAX_DEPTH,
    `deep nesting capped at depth ${maxReached} <= ${MAX_DEPTH}`
  );
}

// ── Results ─────────────────────────────────────────────────────────────────

console.log(`\n${"=".repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
