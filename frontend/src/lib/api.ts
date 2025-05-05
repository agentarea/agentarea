import client from "./client";
import type { components } from "../api/schema";

// Agent API
export const listAgents = async () => {
  const { data, error } = await client.GET("/v1/agents/");
  return { data, error };
};

export const createAgent = async (agent: components["schemas"]["AgentCreate"]) => {
  const { data, error } = await client.POST("/v1/agents/", { body: agent });
  return { data, error };
};

export const getAgent = async (agentId: string) => {
  const { data, error } = await client.GET("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const deleteAgent = async (agentId: string) => {
  const { data, error } = await client.DELETE("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
  });
  return { data, error };
};

export const updateAgent = async (agentId: string, agent: components["schemas"]["AgentUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/agents/{agent_id}", {
    params: { path: { agent_id: agentId } },
    body: agent,
  });
  return { data, error };
};

// MCP Server API
export const listMCPServers = async (params?: {
  status?: string;
  is_public?: boolean;
  tag?: string;
}) => {
  const { data, error } = await client.GET("/v1/mcp-servers/", {
    params: { query: params },
  });
  return { data, error };
};

export const createMCPServer = async (server: components["schemas"]["MCPServerCreate"]) => {
  const { data, error } = await client.POST("/v1/mcp-servers/", { body: server });
  return { data, error };
};

export const getMCPServer = async (serverId: string) => {
  const { data, error } = await client.GET("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

export const deleteMCPServer = async (serverId: string) => {
  const { data, error } = await client.DELETE("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

export const updateMCPServer = async (serverId: string, server: components["schemas"]["MCPServerUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/mcp-servers/{server_id}", {
    params: { path: { server_id: serverId } },
    body: server,
  });
  return { data, error };
};

export const deployMCPServer = async (serverId: string) => {
  const { data, error } = await client.POST("/v1/mcp-servers/{server_id}/deploy", {
    params: { path: { server_id: serverId } },
  });
  return { data, error };
};

// MCP Server Instance API
export const listMCPServerInstances = async (params?: {
  server_id?: string;
  status?: string;
}) => {
  const { data, error } = await client.GET("/v1/mcp-server-instances/", {
    params: { query: params },
  });
  return { data, error };
};

export const createMCPServerInstance = async (instance: components["schemas"]["MCPServerInstanceCreate"]) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/", { body: instance });
  return { data, error };
};

export const getMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.GET("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const deleteMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.DELETE("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const updateMCPServerInstance = async (instanceId: string, instance: components["schemas"]["MCPServerInstanceUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/mcp-server-instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
    body: instance,
  });
  return { data, error };
};

export const startMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/start", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const stopMCPServerInstance = async (instanceId: string) => {
  const { data, error } = await client.POST("/v1/mcp-server-instances/{instance_id}/stop", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

// LLM Model API
export const listLLMModels = async (params?: {
  status?: string;
  is_public?: boolean;
  provider?: string;
}) => {
  const { data, error } = await client.GET("/v1/llm-models/", {
    params: { query: params },
  });
  return { data, error };
};

export type LLMModel = components["schemas"]["LLMModelResponse"];
export type MCPServer = components["schemas"]["MCPServerResponse"];
export type Agent = components["schemas"]["AgentResponse"];

export const createLLMModel = async (model: components["schemas"]["LLMModelCreate"]) => {
  const { data, error } = await client.POST("/v1/llm-models/", { body: model });
  return { data, error };
};

export const getLLMModel = async (modelId: string) => {
  const { data, error } = await client.GET("/v1/llm-models/{model_id}", {
    params: { path: { model_id: modelId } },
  });
  return { data, error };
};

export const deleteLLMModel = async (modelId: string) => {
  const { data, error } = await client.DELETE("/v1/llm-models/{model_id}", {
    params: { path: { model_id: modelId } },
  });
  return { data, error };
};

export const updateLLMModel = async (modelId: string, model: components["schemas"]["LLMModelUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/llm-models/{model_id}", {
    params: { path: { model_id: modelId } },
    body: model,
  });
  return { data, error };
};

// LLM Model Instance API
export const listLLMModelInstances = async (params?: {
  model_id?: string;
  status?: string;
  is_public?: boolean;
}) => {
  const { data, error } = await client.GET("/v1/llm-models/instances/", {
    params: { query: params },
  });
  return { data, error };
};

export const createLLMModelInstance = async (instance: components["schemas"]["LLMModelInstanceCreate"]) => {
  const { data, error } = await client.POST("/v1/llm-models/instances/", { body: instance });
  return { data, error };
};

export const getLLMModelInstance = async (instanceId: string) => {
  const { data, error } = await client.GET("/v1/llm-models/instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const deleteLLMModelInstance = async (instanceId: string) => {
  const { data, error } = await client.DELETE("/v1/llm-models/instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
  });
  return { data, error };
};

export const updateLLMModelInstance = async (instanceId: string, instance: components["schemas"]["LLMModelInstanceUpdate"]) => {
  const { data, error } = await client.PATCH("/v1/llm-models/instances/{instance_id}", {
    params: { path: { instance_id: instanceId } },
    body: instance,
  });
  return { data, error };
};
