import { stripA2UIFromStreamingContent } from "@/lib/events/a2ui";
import type { Part } from "@/lib/events/contract";
import type { CompletedRun } from "@/lib/events/reducer";

export interface ActivityRun {
  id: string;
  parts: Part[];
  completed: boolean;
  terminalType?: string;
  actionCount: number;
  errorCount: number;
}

export type ActivitySegment =
  | { kind: "work"; run: ActivityRun }
  | { kind: "visible" | "answer"; part: Part };

function llmContent(part: Part): string {
  if (part.kind !== "llm") return "";
  const content = part.data.content ?? part.data.chunk;
  return typeof content === "string"
    ? stripA2UIFromStreamingContent(content).trim()
    : "";
}

function hasLlmContent(part: Part): boolean {
  return llmContent(part).length > 0;
}

/** Whether the rendered transcript already owns assistant-facing prose. */
export function hasVisibleAssistantContent(
  segments: ActivitySegment[]
): boolean {
  return segments.some((segment) =>
    segment.kind === "work"
      ? segment.run.parts.some(hasLlmContent)
      : hasLlmContent(segment.part)
  );
}

export function lastVisibleAssistantContent(
  segments: ActivitySegment[]
): string | null {
  for (const segment of [...segments].reverse()) {
    const parts =
      segment.kind === "work"
        ? [...segment.run.parts].reverse()
        : [segment.part];
    const part = parts.find(hasLlmContent);
    if (part) return llmContent(part);
  }
  return null;
}

export function shouldRenderConversationFallback(
  eventsLoading: boolean,
  segments: ActivitySegment[]
): boolean {
  return !eventsLoading && !hasVisibleAssistantContent(segments);
}

function hasText(part: Part): boolean {
  return (
    part.kind === "llm" &&
    part.eventType === "llm.call.completed" &&
    llmContent(part).length > 0
  );
}

function failed(part: Part): boolean {
  if (part.kind === "llm") return part.eventType === "llm.call.failed";
  if (part.kind !== "tool" || part.eventType === "tool.call") return false;
  return typeof part.data.exit_code === "number"
    ? part.data.exit_code !== 0
    : part.data.success === false;
}

/** Terminal snapshots close runs; an LLM response alone never closes work. */
export function buildActivitySegments(
  parts: Part[],
  completedRuns: CompletedRun[]
): ActivitySegment[] {
  const byId = new Map(parts.map((part) => [part.partId, part]));
  const consumed = new Set(completedRuns.flatMap((run) => run.partIds));
  const runs = completedRuns
    .map((run) => ({
      ...run,
      parts: run.partIds
        .map((id) => byId.get(id))
        .filter((part): part is Part => !!part),
      completed: true,
    }))
    .filter(
      (run) =>
        run.parts.length > 0 ||
        run.partIds.length === 0 ||
        Boolean(run.terminalAnswer?.trim())
    );
  const active = parts.filter((part) => !consumed.has(part.partId));
  if (active.length > 0) {
    runs.push({
      id: `run-${completedRuns.length + 1}`,
      partIds: active.map((part) => part.partId),
      parts: active,
      completed: false,
      terminalType: "",
      terminalMessage: null,
      terminalAnswer: null,
    });
  }

  const segments: ActivitySegment[] = [];
  for (const run of runs) {
    let answer: Part | undefined;
    if (run.completed) {
      const text = run.terminalAnswer?.trim();
      answer = [...run.parts]
        .reverse()
        .find((part) => hasText(part) && (!text || llmContent(part) === text));
      if (text && !answer) {
        answer = [...run.parts]
          .reverse()
          .find(
            (part) =>
              part.kind === "llm" &&
              part.eventType === "llm.call.chunk" &&
              llmContent(part) === text
          );
      }
      if (text && !answer) {
        answer = {
          partId: `${run.id}-answer`,
          kind: "llm",
          eventType: "llm.call.completed",
          data: { content: run.terminalAnswer },
        };
      }
    }
    const answerPart =
      answer && answer.eventType === "llm.call.chunk"
        ? {
            ...answer,
            eventType: "llm.call.completed",
            data: {
              ...answer.data,
              content: run.terminalAnswer ?? llmContent(answer),
            },
          }
        : answer;
    let work: Part[] = [];
    const flush = () => {
      const tools = work.filter((part) => part.kind === "tool");
      if (tools.length > 0) {
        segments.push({
          kind: "work",
          run: {
            // The first tool is stable when the final answer leaves the trace.
            id: `${run.id}-work-${tools[0].partId}`,
            parts: work,
            completed: run.completed,
            terminalType: run.terminalType,
            actionCount: tools.length,
            errorCount: work.filter(failed).length,
          },
        });
      } else {
        segments.push(
          ...work.map((part): ActivitySegment => ({ kind: "visible", part }))
        );
      }
      work = [];
    };
    for (const part of run.parts) {
      if (part === answer) continue;
      if (
        part.kind === "form" ||
        part.kind === "artifact" ||
        part.kind === "a2ui"
      ) {
        flush();
        segments.push({ kind: "visible", part });
      } else {
        work.push(part);
      }
    }
    flush();
    if (answerPart) segments.push({ kind: "answer", part: answerPart });
  }
  return segments;
}
