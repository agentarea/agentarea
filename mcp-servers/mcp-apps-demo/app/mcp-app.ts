import {
  App,
  applyDocumentTheme,
  applyHostStyleVariables,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/client";
import type { DatasetSnapshot } from "../server/dataset.ts";
import { LEAD_STATUSES } from "../shared/leads.ts";

const datasetEl = document.getElementById("dataset")!;
const summaryEl = document.getElementById("summary")!;
const columnsEl = document.getElementById("columns")!;
const rowsEl = document.getElementById("rows")!;
const errorEl = document.getElementById("error")!;
const refreshBtn = document.getElementById("refresh") as HTMLButtonElement;

const CELL_CLASS: Record<string, string> = { id: "col-id", company: "col-company" };

const app = new App({ name: "Leads view", version: "0.1.0" });

function snapshotOf(result: CallToolResult): DatasetSnapshot {
  if (result.isError) {
    const message = result.content
      .map((block) => (block.type === "text" ? block.text : ""))
      .join(" ");
    throw new Error(message || "the tool reported an error");
  }
  return result.structuredContent as DatasetSnapshot;
}

function showError(error: unknown) {
  errorEl.textContent = error instanceof Error ? error.message : String(error);
  errorEl.hidden = false;
}

async function setStatus(id: string, select: HTMLSelectElement, previous: string) {
  const row = select.closest("tr")!;
  row.setAttribute("aria-busy", "true");
  select.disabled = true;
  try {
    const result = await app.callServerTool({
      name: "set_lead_status",
      arguments: { id, status: select.value },
    });
    render(snapshotOf(result));
  } catch (error) {
    showError(error);
    select.value = previous;
    select.disabled = false;
    row.removeAttribute("aria-busy");
  }
}

function dot(): HTMLSpanElement {
  const el = document.createElement("span");
  el.className = "dot";
  return el;
}

function statusControl(id: string, current: string): HTMLElement {
  const control = document.createElement("span");
  control.className = "status";
  control.dataset.status = current;
  const select = document.createElement("select");
  select.setAttribute("aria-label", `Status of lead ${id}`);
  for (const status of LEAD_STATUSES) {
    select.add(new Option(status, status, false, status === current));
  }
  select.addEventListener("change", () => setStatus(id, select, current));
  control.append(dot(), select);
  return control;
}

function summaryItem(status: string, count: number): HTMLLIElement {
  const item = document.createElement("li");
  item.dataset.status = status;
  const label = document.createElement("span");
  label.textContent = status;
  const value = document.createElement("strong");
  value.textContent = String(count);
  item.append(dot(), label, value);
  return item;
}

// Rows come from a dataset the app does not control, so cells are set as text,
// never parsed as markup.
function render(snapshot: DatasetSnapshot) {
  errorEl.hidden = true;
  const rowCount = snapshot.rows.length;
  datasetEl.textContent = `${snapshot.dataset} · ${rowCount} ${rowCount === 1 ? "row" : "rows"}`;

  const counts: Record<string, number> = Object.fromEntries(LEAD_STATUSES.map((s) => [s, 0]));
  for (const row of snapshot.rows) {
    if (row.status in counts) counts[row.status] += 1;
  }
  summaryEl.replaceChildren(...LEAD_STATUSES.map((status) => summaryItem(status, counts[status])));

  columnsEl.replaceChildren(
    ...snapshot.columns.map((column) => {
      const th = document.createElement("th");
      th.textContent = column;
      return th;
    }),
  );

  if (rowCount === 0) {
    const td = document.createElement("td");
    td.className = "empty";
    td.colSpan = snapshot.columns.length;
    td.textContent = "This dataset has no rows yet.";
    const tr = document.createElement("tr");
    tr.append(td);
    rowsEl.replaceChildren(tr);
    return;
  }

  rowsEl.replaceChildren(
    ...snapshot.rows.map((row) => {
      const tr = document.createElement("tr");
      for (const column of snapshot.columns) {
        const td = document.createElement("td");
        if (column === "status") {
          td.append(statusControl(row.id, row.status));
        } else {
          td.className = CELL_CLASS[column] ?? "col-muted";
          td.textContent = row[column];
        }
        tr.append(td);
      }
      return tr;
    }),
  );
}

function applyHostContext(ctx: McpUiHostContext) {
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
}

app.ontoolresult = (result) => {
  try {
    render(snapshotOf(result));
  } catch (error) {
    showError(error);
  }
};
app.ontoolcancelled = (params) => showError(`Cancelled: ${params.reason ?? "no reason given"}`);
app.onhostcontextchanged = applyHostContext;
app.onerror = console.error;

refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  try {
    render(snapshotOf(await app.callServerTool({ name: "show_leads", arguments: {} })));
  } catch (error) {
    showError(error);
  } finally {
    refreshBtn.disabled = false;
  }
});

app.connect().then(() => {
  const hostContext = app.getHostContext();
  if (hostContext) applyHostContext(hostContext);
}, showError);
