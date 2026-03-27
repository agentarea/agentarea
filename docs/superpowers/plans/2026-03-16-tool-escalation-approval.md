# Tool Escalation & Human Approval Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken single-tool-pause approval mechanism with per-tool independent escalation that supports approve/deny-with-comment, rendered as inline chat messages.

**Architecture:** The workflow tracks `pending_escalations` as a dict keyed by `escalation_id`. Each tool that needs approval gets its own escalation entry. Non-escalated tools execute immediately. A new `resolve_escalation` signal resolves individual escalations. The frontend renders `HumanApprovalRequested` events as interactive chat cards with Approve/Deny+comment buttons. A new `resolve_escalation` API endpoint forwards decisions to Temporal.

**Tech Stack:** Python/Temporal (workflow signals, wait_condition), FastAPI (new endpoint), Next.js/React (new chat component), SSE (existing event pipeline)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `agentarea-platform/libs/execution/agentarea_execution/workflows/models.py` | Add `PendingEscalation` model |
| Modify | `agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py` | Add `HUMAN_APPROVAL_DENIED` event type |
| Modify | `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py` | Refactor approval: per-tool escalation tracking, new signal, deny handling |
| Modify | `agentarea-platform/apps/api/agentarea_api/api/v1/agents_tasks.py` | Add `POST .../resolve-escalation` endpoint |
| Modify | `agentarea-webapp/src/components/Chat/types.ts` | Add `ApprovalRequestData` type |
| Create | `agentarea-webapp/src/components/Chat/componets/ApprovalRequestMessage.tsx` | Interactive approve/deny chat card |
| Modify | `agentarea-webapp/src/components/Chat/MessageComponents.tsx` | Register `approval_request` renderer |
| Modify | `agentarea-webapp/src/components/Chat/EventParser.ts` | Parse `HumanApprovalRequested` / `HumanApprovalReceived` / `HumanApprovalDenied` |
| Modify | `agentarea-webapp/src/components/Chat/constants/eventTypes.ts` | Add approval event constants |
| Modify | `agentarea-webapp/src/components/Chat/handlers/eventHandlers.ts` | Handle approval events in SSE pipeline |
| Modify | `agentarea-webapp/src/app/(main)/agents/[id]/tasks/[taskId]/actions.ts` | Add `resolveEscalation` server action |
| Modify | `agentarea-webapp/src/lib/api-factory.ts` | Add `resolveEscalation` API call |
| Modify | `agentarea-webapp/src/lib/browser-api.ts` | Add `resolveEscalation` browser API call |
| Modify | `agentarea-webapp/src/lib/api.ts` | Export `resolveEscalation` |
| Modify | `agentarea-webapp/src/types/events.ts` | Add `HumanApprovalDenied` event type |

---

## Chunk 1: Backend — Models, Constants & Workflow Refactor

### Task 1: Add PendingEscalation model

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/models.py`

- [ ] **Step 1: Add PendingEscalation to models.py**

Add after `ToolResult` class:

```python
class PendingEscalation(BaseModel):
    """Tracks a single tool call awaiting human approval."""

    escalation_id: str
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False
    approved: bool | None = None
    deny_comment: str | None = None
```

### Task 2: Add HUMAN_APPROVAL_DENIED constant

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/constants.py`

- [ ] **Step 1: Add denied event type**

After `HUMAN_APPROVAL_RECEIVED` line, add:

```python
    HUMAN_APPROVAL_DENIED: Final[str] = "HumanApprovalDenied"
```

### Task 3: Refactor workflow approval mechanism

**Files:**
- Modify: `agentarea-platform/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py`

This is the core change. The existing code uses a global `_paused` flag and `resume_execution` signal. We need per-tool escalation tracking.

- [ ] **Step 1: Add escalation state to `__init__`**

In `AgentExecutionWorkflow.__init__`, add:

```python
        self._pending_escalations: dict[str, PendingEscalation] = {}
```

Add `PendingEscalation` to the imports from `.models`.

- [ ] **Step 2: Add `resolve_escalation` signal**

After the existing `resume_execution` signal, add:

```python
    @workflow.signal
    async def resolve_escalation(self, escalation_id: str, approved: bool, comment: str = "") -> None:
        """Signal to approve or deny a specific tool escalation."""
        if escalation_id in self._pending_escalations:
            esc = self._pending_escalations[escalation_id]
            esc.resolved = True
            esc.approved = approved
            esc.deny_comment = comment if not approved else None
            workflow.logger.info(
                f"Escalation {escalation_id} resolved: approved={approved}"
                + (f" comment='{comment}'" if comment else "")
            )
```

- [ ] **Step 3: Refactor `_execute_mcp_tool` approval block**

Replace the existing approval block (lines ~988-1023) with per-escalation logic. The key change: instead of setting `self._paused = True` and waiting on `not self._paused`, we create a `PendingEscalation`, emit the event with `escalation_id`, and wait on that specific escalation being resolved.

```python
        # Approval gating before starting the tool activity
        approval_required = bool(
            self.state.goal and getattr(self.state.goal, "requires_human_approval", False)
        ) or self._tool_requires_approval(tool_name)

        if approval_required:
            import uuid as _uuid

            escalation_id = str(_uuid.uuid4())
            escalation = PendingEscalation(
                escalation_id=escalation_id,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                tool_args=tool_args,
            )
            self._pending_escalations[escalation_id] = escalation

            self.state.status = ExecutionStatus.WAITING_FOR_APPROVAL

            # Publish approval requested event with escalation_id
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_REQUESTED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                    "arguments": tool_args,
                    "message": f"Tool '{tool_name}' requires human approval",
                },
            )
            await self._publish_events_immediately()

            # Wait for THIS specific escalation to be resolved
            await workflow.wait_condition(lambda: escalation.resolved)

            if not escalation.approved:
                # Denied — add tool result as denied, don't execute
                deny_msg = escalation.deny_comment or "Denied by user"
                self.event_manager.add_event(
                    EventTypes.HUMAN_APPROVAL_DENIED,
                    {
                        "escalation_id": escalation_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "iteration": self.state.current_iteration,
                        "comment": deny_msg,
                    },
                )
                await self._publish_events_immediately()

                # Add denied result as tool response so LLM knows
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=f"Tool call denied by human operator: {deny_msg}",
                        tool_call_id=tool_call.id,
                        name=tool_name,
                    )
                )

                # Clean up and update status
                del self._pending_escalations[escalation_id]
                if not self._pending_escalations:
                    self.state.status = ExecutionStatus.EXECUTING
                return

            # Approved — continue to execute
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_RECEIVED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()
            del self._pending_escalations[escalation_id]
            if not self._pending_escalations:
                self.state.status = ExecutionStatus.EXECUTING
```

- [ ] **Step 4: Add escalation info to query state**

In the `get_state` query method (around line 1856), add `pending_escalations`:

```python
            "pending_escalations": {
                eid: {"tool_name": e.tool_name, "tool_call_id": e.tool_call_id, "resolved": e.resolved}
                for eid, e in self._pending_escalations.items()
            },
```

### Task 4: Add resolve-escalation API endpoint

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/agents_tasks.py`

- [ ] **Step 1: Add request model**

```python
class EscalationResolution(BaseModel):
    escalation_id: str
    approved: bool
    comment: str = ""
```

- [ ] **Step 2: Add endpoint**

After the existing resume endpoint, add:

```python
@router.post("/{task_id}/resolve-escalation")
async def resolve_escalation(
    agent_id: UUID,
    task_id: UUID,
    data: EscalationResolution,
    user_context: UserContext = Depends(get_user_context),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict:
    """Resolve a pending tool escalation (approve or deny with optional comment)."""
    workflow_id = f"agent-execution-{task_id}"
    handle = temporal_client.get_workflow_handle(workflow_id)
    await handle.signal(
        "resolve_escalation",
        args=[data.escalation_id, data.approved, data.comment],
    )
    return {
        "status": "resolved",
        "escalation_id": data.escalation_id,
        "approved": data.approved,
    }
```

- [ ] **Step 3: Verify imports**

Ensure `Client` from `temporalio.client` and `get_temporal_client` dependency are available. Check existing pause/resume endpoints for the pattern.

---

## Chunk 2: Frontend — Event Types, Chat Component & API Integration

### Task 5: Add frontend event constants and types

**Files:**
- Modify: `agentarea-webapp/src/components/Chat/constants/eventTypes.ts`
- Modify: `agentarea-webapp/src/components/Chat/types.ts`
- Modify: `agentarea-webapp/src/types/events.ts`

- [ ] **Step 1: Add event constants**

In `eventTypes.ts`, add after tool events:

```typescript
// Approval events
export const EVENT_HUMAN_APPROVAL_REQUESTED = "HumanApprovalRequested";
export const EVENT_HUMAN_APPROVAL_RECEIVED = "HumanApprovalReceived";
export const EVENT_HUMAN_APPROVAL_DENIED = "HumanApprovalDenied";
```

Also add to `CANONICAL_EVENT_TYPES`:

```typescript
  // Approval
  HUMAN_APPROVAL_REQUESTED: EVENT_HUMAN_APPROVAL_REQUESTED,
  HUMAN_APPROVAL_RECEIVED: EVENT_HUMAN_APPROVAL_RECEIVED,
  HUMAN_APPROVAL_DENIED: EVENT_HUMAN_APPROVAL_DENIED,
```

- [ ] **Step 2: Add ApprovalRequestData type**

In `types.ts`, add:

```typescript
// Approval Request Message
export interface ApprovalRequestData extends BaseMessageData {
  escalation_id: string;
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
  message: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
}
```

Add to `MessageComponentType` union:

```typescript
  | { type: "approval_request"; data: ApprovalRequestData }
```

- [ ] **Step 3: Add HumanApprovalDenied to events.ts**

In `WorkflowEventType`, add `"HumanApprovalDenied"`.

In `EVENT_TYPE_CONFIG`, add:

```typescript
  HumanApprovalDenied: {
    title: "Approval Denied",
    level: "warning",
    icon: "user-x",
    color: "red",
  },
```

Add to the `eventTypeMap` in `mapSSEToDisplayEvent`:

```typescript
    human_approval_denied: "HumanApprovalDenied",
    humanapprovaldenied: "HumanApprovalDenied",
```

### Task 6: Create ApprovalRequestMessage component

**Files:**
- Create: `agentarea-webapp/src/components/Chat/componets/ApprovalRequestMessage.tsx`

- [ ] **Step 1: Create the component**

```tsx
"use client";

import React, { useState } from "react";
import { ShieldAlert, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface ApprovalRequestData {
  escalation_id: string;
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
  message: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
}

interface Props {
  data: ApprovalRequestData;
  onResolve?: (escalationId: string, approved: boolean, comment: string) => void;
}

const ApprovalRequestMessage: React.FC<Props> = ({ data, onResolve }) => {
  const [showDenyForm, setShowDenyForm] = useState(false);
  const [denyComment, setDenyComment] = useState("");
  const [resolving, setResolving] = useState(false);

  const handleApprove = async () => {
    setResolving(true);
    onResolve?.(data.escalation_id, true, "");
  };

  const handleDeny = async () => {
    setResolving(true);
    onResolve?.(data.escalation_id, false, denyComment);
  };

  const isResolved = data.resolved;

  return (
    <MessageWrapper type="tool-call">
      <BaseMessage
        headerLeft={
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-500" />
            <span>Approval Required: {data.tool_name}</span>
          </div>
        }
        headerRight={
          isResolved ? (
            <span className={data.approved ? "text-green-600" : "text-red-600"}>
              {data.approved ? "Approved" : "Denied"}
            </span>
          ) : (
            <span className="animate-pulse text-amber-600">Waiting...</span>
          )
        }
        collapsed={false}
      >
        <div className="space-y-3">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {data.message}
          </p>

          {Object.keys(data.arguments).length > 0 && (
            <details className="cursor-pointer text-xs text-gray-500">
              <summary className="hover:text-gray-700 dark:hover:text-gray-300">
                Arguments
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-gray-100 p-2 dark:bg-gray-800">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          )}

          {!isResolved && !resolving && (
            <div className="flex items-start gap-2">
              <Button
                size="sm"
                variant="default"
                onClick={handleApprove}
                className="bg-green-600 hover:bg-green-700"
              >
                <Check className="mr-1 h-3 w-3" />
                Approve
              </Button>

              {!showDenyForm ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowDenyForm(true)}
                  className="border-red-300 text-red-600 hover:bg-red-50"
                >
                  <X className="mr-1 h-3 w-3" />
                  Deny
                </Button>
              ) : (
                <div className="flex flex-1 flex-col gap-2">
                  <Textarea
                    placeholder="Reason for denial (optional)"
                    value={denyComment}
                    onChange={(e) => setDenyComment(e.target.value)}
                    className="min-h-[60px] text-sm"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={handleDeny}
                    >
                      Deny
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowDenyForm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {resolving && !isResolved && (
            <p className="animate-pulse text-sm text-gray-500">Sending decision...</p>
          )}

          {isResolved && !data.approved && data.deny_comment && (
            <p className="text-sm text-red-600">
              Reason: {data.deny_comment}
            </p>
          )}
        </div>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ApprovalRequestMessage;
```

### Task 7: Wire up EventParser, MessageComponents, and event handler

**Files:**
- Modify: `agentarea-webapp/src/components/Chat/EventParser.ts`
- Modify: `agentarea-webapp/src/components/Chat/MessageComponents.tsx`
- Modify: `agentarea-webapp/src/components/Chat/handlers/eventHandlers.ts`

- [ ] **Step 1: Add approval parsing to EventParser.ts**

In `parseEventToMessage`, add cases before the `default`:

```typescript
    case "HumanApprovalRequested": {
      const originalData = eventData.original_data || eventData;
      return {
        type: "approval_request",
        data: {
          ...baseData,
          escalation_id: originalData.escalation_id || eventData.escalation_id,
          tool_name: originalData.tool_name || eventData.tool_name,
          tool_call_id: originalData.tool_call_id || eventData.tool_call_id,
          arguments: originalData.arguments || eventData.arguments || {},
          message: originalData.message || eventData.message || "Approval required",
        },
      };
    }

    case "HumanApprovalDenied":
    case "HumanApprovalReceived":
      // These update existing approval messages, handled in eventHandlers
      return null;
```

In `shouldDisplayEvent`, add `"HumanApprovalRequested"` to `displayableEvents`.

- [ ] **Step 2: Add renderer to MessageComponents.tsx**

Import the new component and add a case:

```typescript
import ApprovalRequestMessage from "./componets/ApprovalRequestMessage";
```

In the switch:

```typescript
    case "approval_request":
      return (
        <ApprovalRequestMessage
          data={message.data}
          key={message.data.id}
          onResolve={message.data._onResolve}
        />
      );
```

Note: We'll need to inject `_onResolve` callback when creating messages. This will be done in the event handler.

- [ ] **Step 3: Handle approval resolution events in eventHandlers.ts**

Import the new constants and add handling for `HumanApprovalReceived` and `HumanApprovalDenied` that update existing approval messages:

```typescript
import {
  EVENT_HUMAN_APPROVAL_RECEIVED,
  EVENT_HUMAN_APPROVAL_DENIED,
} from "../constants/eventTypes";
```

Add before the default case in the event handler:

```typescript
    // Handle approval resolution - update existing approval message
    if (
      cleanEventType === EVENT_HUMAN_APPROVAL_RECEIVED ||
      cleanEventType === EVENT_HUMAN_APPROVAL_DENIED
    ) {
      const escalationId = event.data?.escalation_id || event.data?.original_data?.escalation_id;
      if (escalationId) {
        setMessages((prev) =>
          prev.map((msg) => {
            if (
              "type" in msg &&
              msg.type === "approval_request" &&
              msg.data.escalation_id === escalationId
            ) {
              return {
                ...msg,
                data: {
                  ...msg.data,
                  resolved: true,
                  approved: cleanEventType === EVENT_HUMAN_APPROVAL_RECEIVED,
                  deny_comment: event.data?.comment || event.data?.original_data?.comment,
                },
              };
            }
            return msg;
          })
        );
      }
      return;
    }
```

### Task 8: Add API integration for resolve-escalation

**Files:**
- Modify: `agentarea-webapp/src/lib/api-factory.ts`
- Modify: `agentarea-webapp/src/lib/browser-api.ts`
- Modify: `agentarea-webapp/src/lib/api.ts`
- Modify: `agentarea-webapp/src/app/(main)/agents/[id]/tasks/[taskId]/actions.ts`

- [ ] **Step 1: Add to api-factory.ts**

After `resumeAgentTask`:

```typescript
    resolveEscalation: async (
      agentId: string,
      taskId: string,
      escalationId: string,
      approved: boolean,
      comment: string = ""
    ) => {
      const { data, error } = await client.POST(
        "/v1/agents/{agent_id}/tasks/{task_id}/resolve-escalation",
        {
          params: { path: { agent_id: agentId, task_id: taskId } },
          body: { escalation_id: escalationId, approved, comment },
        }
      );
      return { data, error };
    },
```

- [ ] **Step 2: Add to browser-api.ts**

Same pattern as `resumeAgentTask`, with the resolve-escalation endpoint.

```typescript
export const resolveEscalation = async (
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) => {
  const { data, error } = await browserClient.POST(
    "/v1/agents/{agent_id}/tasks/{task_id}/resolve-escalation",
    {
      params: { path: { agent_id: agentId, task_id: taskId } },
      body: { escalation_id: escalationId, approved, comment },
    }
  );
  return { data, error };
};
```

- [ ] **Step 3: Export from api.ts**

Add `resolveEscalation` to both imports and exports.

- [ ] **Step 4: Add server action**

In `actions.ts`:

```typescript
import { resolveEscalation as resolveEscalationApi } from "@/lib/api";

export async function resolveEscalation(
  agentId: string,
  taskId: string,
  escalationId: string,
  approved: boolean,
  comment: string = ""
) {
  return await resolveEscalationApi(agentId, taskId, escalationId, approved, comment);
}
```

### Task 9: Wire onResolve callback through the chat

**Files:**
- Modify: `agentarea-webapp/src/components/Chat/AgentChat.tsx` (or wherever messages are rendered)

- [ ] **Step 1: Pass onResolve to message rendering**

The `AgentChat` component needs to provide the `onResolve` callback that calls the `resolveEscalation` server action. When rendering `approval_request` messages, inject the callback. This depends on the AgentChat structure — the callback should call the server action with the current `agentId` and `taskId` from props.

The simplest approach: in the `MessageRenderer` or in `AgentChat`, check if the message is `approval_request` and pass the callback as a prop. The callback calls `resolveEscalation(agentId, taskId, escalationId, approved, comment)`.

---

## Chunk 3: SSE Registration & Testing

### Task 10: Register approval events in SSE listener

**Files:**
- Modify: `agentarea-webapp/src/hooks/useSSE.ts`

- [ ] **Step 1: Add event types to SSE listener**

Add `"human_approval_denied"` to the `eventTypes` array.

### Task 11: Manual end-to-end testing

- [ ] **Step 1: Configure an agent tool with `requires_user_confirmation: true`**

In the agent configuration, set a tool's settings to include `requires_user_confirmation: true`.

- [ ] **Step 2: Create a task that triggers the tool**

Send a message to the agent that will cause it to call the escalation-requiring tool.

- [ ] **Step 3: Verify the approval card appears in chat**

The `HumanApprovalRequested` event should render as an interactive card.

- [ ] **Step 4: Test approve flow**

Click Approve — tool executes, agent continues.

- [ ] **Step 5: Test deny flow**

Click Deny, enter comment — tool is skipped with denial message, agent sees it and adapts.

- [ ] **Step 6: Test multiple escalations**

Trigger a batch with 2+ escalated tools — each should have its own independent card.
