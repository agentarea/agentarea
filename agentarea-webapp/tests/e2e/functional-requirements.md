# Playwright Functional Requirements Coverage

This is the executable coverage map for real-stack Playwright tests. The source
of truth for IDs and acceptance criteria is `requirements.ts`; skipped tests in
`functional-requirements.todo.real.spec.ts` intentionally keep uncovered
requirements visible in Playwright output.

| ID    | Priority | Status      | Coverage                                                              |
| ----- | -------- | ----------- | --------------------------------------------------------------------- |
| FR-01 | must     | implemented | Real Kratos auth, OpenAPI, protected API, authenticated browser shell |
| FR-02 | must     | implemented | Real workspace invitation create/accept/member listing                |
| FR-03 | must     | implemented | Agent create/detail/edit/list/delete through the real API             |
| FR-04 | must     | implemented | Provider config secret masking, tenant model spec, model instance, failed provider test state |
| FR-05 | must     | implemented | Real agent task creation plus agent/global task list visibility       |
| FR-06 | must     | implemented | Real task SSE stream emits connected and task-created/error events    |
| FR-07 | must     | implemented | MCP command spec validation, instance create, verification state visibility |
| FR-08 | must     | implemented | OpenAPI inline spec preview/invalid validation/create/agent attachment |
| FR-09 | must     | implemented | Webhook trigger enable/disable/public execution/execution history     |
| FR-10 | must     | implemented | Real Kratos registration email captured in Mailpit                    |
| FR-11 | should   | todo        | Network topology                                                      |
| FR-12 | should   | todo        | Skills and catalog flows                                              |
| FR-13 | should   | todo        | Projects and files                                                    |
| FR-14 | should   | todo        | API keys and secrets                                                  |
| FR-15 | should   | todo        | Policies, approvals, and governance audit                             |
| FR-16 | should   | todo        | Workspace import and export                                           |
| FR-17 | should   | todo        | Dashboard, inbox, budgets, and operational views                      |
| FR-18 | must     | todo        | Long conversation context management                                  |
| FR-19 | must     | todo        | Agent task delegation                                                 |

Run against the current local stand:

```bash
pnpm run test:e2e:current-stand
```

Run with Playwright starting the webapp and using a separately running real
backend/Kratos/Mailpit stack:

```bash
pnpm run test:e2e:real
```
