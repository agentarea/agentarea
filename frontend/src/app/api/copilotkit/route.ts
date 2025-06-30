import { CopilotRuntime, HttpAgent } from "@copilotkit/runtime";
import { copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime/nextjs";
import { NextRequest } from "next/server";

// Create HttpAgent that connects to our AG-UI endpoint
const agentAreaAgent = new HttpAgent({
  url: "http://localhost:8000/v1/protocol/ag-ui", // Your AG-UI endpoint
  headers: {
    "Content-Type": "application/json",
  },
});

// Initialize CopilotKit runtime
const runtime = new CopilotRuntime({
  agents: {
    agentAreaAgent,
  },
});

// Export Next.js API route handlers
export const { GET, POST } = copilotRuntimeNextJSAppRouterEndpoint({
  runtime,
  endpoint: "/api/copilotkit",
}); 