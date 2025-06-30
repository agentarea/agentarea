# MCP Server Instance Management Implementation Plan

This document outlines the implementation plan for the end-to-end flow for creating and managing MCP server instances, triggered from the frontend.

## 🎯 High-Level Goal

The primary goal is to allow a user to create a new `mcp-server-instance` from a predefined `mcp-server-specification` (template) through the frontend UI. The request will be handled by the `core/agentarea` backend, which will then communicate with the `go-mcp-manager` service to provision the actual container instance.

## 🏗️ Component Breakdown & Implementation Steps

### Step 1: `core/agentarea` - The Central Controller

The `core/agentarea` Python application will act as the main API and orchestration layer.

#### 1.1. MCP Manager Client (`core/agentarea/modules/mcp/client.py`) - **✅ DONE**

- **Responsibility:** Communicate with the `go-mcp-manager` REST API.
- **Implementation:**
    - ✅ Create an `McpManagerClient` class using `httpx`
    - ✅ Implement methods for each `go-mcp-manager` endpoint:
        - `get_templates()` → `GET /templates`
        - `create_container(service_name, template, ...)` → `POST /containers`
        - `get_container(service_name)` → `GET /containers/{service}`
        - `delete_container(service_name)` → `DELETE /containers/{service}`
    - ✅ Implement robust error handling (e.g., custom exceptions for HTTP errors)
    - ✅ Use Pydantic models to serialize requests and deserialize responses
    - ✅ Use a singleton pattern (`get_mcp_manager_client`) to reuse the client instance

#### 1.2. Application Service (`core/agentarea/modules/mcp/application/service.py`) - **✅ DONE**

- **Responsibility:** Contain the business logic for managing server instances.
- **Implementation:**
    - ✅ Create an `MCPServerInstanceService` class
    - ✅ Inject the `McpManagerClient` and the `MCPServerInstanceRepository`
    - ✅ Implement the core method `create_instance_from_template(name, template, ...)`:
        1. Create an `MCPServerInstance` record in the database with `status: 'requested'`
        2. Set status to `'creating'`
        3. Call `mcp_manager_client.create_container()`
        4. On success, update the instance record with the container details (ID, port, URL) and set `status: 'created'`
        5. On failure, update the instance record with the error message and set `status: 'failed'`
    - ✅ Implement other methods like `get_instance()`, `list_instances()`, and `delete_instance()`

#### 1.3. API Handlers (`core/agentarea/modules/mcp/handlers.py`) - **🚧 IN PROGRESS**

- **Responsibility:** Expose the instance management functionality via a REST API.
- **Implementation:**
    - ✅ Remove the deprecation notice
    - ✅ Create a new FastAPI `APIRouter`
    - 🔄 Define the following endpoints:
        - `POST /mcp/instances`: Creates a new server instance
            - **Request Body:** A Pydantic model (`MCPServerInstanceCreateRequest`) containing `name`, `template`, `environment`, etc.
            - **Logic:** Calls `MCPServerInstanceService.create_instance_from_template()`
            - **Response:** The created `MCPServerInstance` details
        - `GET /mcp/instances`: Lists all server instances
        - `GET /mcp/instances/{instance_id}`: Gets details for a specific instance
        - `DELETE /mcp/instances/{instance_id}`: Deletes a server instance

#### 1.4. API Router Registration (`core/main.py`) - **🔄 PENDING**

- **Responsibility:** Make the new MCP API endpoints available.
- **Implementation:**
    - Import the router from `handlers.py`
    - Register it with the main FastAPI app using `app.include_router()`

### Step 2: `go-mcp-manager` - The Container Provisioner - **✅ COMPLETE**

The `go-mcp-manager` service is largely complete and functional. No major changes are needed, but we rely on its existing API.

- **`POST /containers`:** Expects a `CreateContainerRequest` with `service_name` and `template`. It creates a container and returns its details.
- **`GET /templates`:** Returns a list of available container templates. This can be used to populate the frontend UI.

### Step 3: Frontend Application - **🔄 PENDING**

- **Responsibility:** Provide the user interface for creating and managing MCP server instances.
- **Implementation:**
    - 🔄 Create a form for creating a new instance
        - The "template" field should be a dropdown populated by calling the `core/agentarea` backend, which in turn calls `go-mcp-manager`'s `/templates` endpoint
        - Allow the user to specify a name and environment variables
    - 🔄 On form submission, make a `POST` request to the new `/mcp/instances` endpoint on the `core/agentarea` backend
    - 🔄 Display the status of the instances (e.g., "creating", "running", "failed")
    - 🔄 Provide options to view instance details and delete instances

## 🔄 Data Flow Diagram

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant AgentArea API (Python)
    participant McpManager (Go)
    participant Database (Postgres)
    participant Docker/Podman

    User->>Frontend: Fills out "Create Instance" form
    Frontend->>AgentArea API (Python): POST /mcp/instances
    AgentArea API (Python)->>Database (Postgres): CREATE MCPServerInstance (status: 'requested')
    AgentArea API (Python)->>Database (Postgres): UPDATE MCPServerInstance (status: 'creating')
    AgentArea API (Python)->>McpManager (Go): POST /containers
    McpManager (Go)->>Docker/Podman: Start Container
    Docker/Podman-->>McpManager (Go): Container Details
    McpManager (Go)-->>AgentArea API (Python): Return Container Details
    AgentArea API (Python)->>Database (Postgres): UPDATE MCPServerInstance with details (status: 'created')
    AgentArea API (Python)-->>Frontend: Return MCPServerInstance JSON
    Frontend-->>User: Display "Instance Created" message
```

## 📋 Next Steps

### Immediate Actions (High Priority)
1. **🔄 Implement `handlers.py` in `core/agentarea`**
2. **🔄 Register the new API router in `main.py`**
3. **🔄 Test the backend API endpoints**

### Short Term (Medium Priority)
4. **🔄 Develop the frontend components for instance management**
5. **🔄 Thoroughly test the end-to-end flow**
6. **🔄 Add error handling and validation**

### Long Term (Low Priority)
7. **📋 Add monitoring and logging for instance lifecycle**
8. **📋 Implement bulk operations (create/delete multiple instances)**
9. **📋 Add instance health checks and auto-recovery**
10. **📋 (Future) Deprecate and remove the old event-based creation logic in `MCPServerInstanceService` once the new direct-call method is stable**

## ✅ Success Criteria

- [ ] Users can create MCP server instances from the frontend
- [ ] Instance status is properly tracked and displayed
- [ ] Containers are successfully provisioned via `go-mcp-manager`
- [ ] Error states are handled gracefully
- [ ] End-to-end flow is fully tested

## 🔍 Testing Strategy

### Unit Tests
- Test `MCPServerInstanceService` methods
- Test API endpoint handlers
- Mock external dependencies

### Integration Tests  
- Test communication between `agentarea` and `go-mcp-manager`
- Test database operations and state transitions
- Test container lifecycle management

### End-to-End Tests
- Test complete user flow from frontend to container creation
- Test error scenarios and recovery
- Test instance management operations (list, delete, etc.)

---

*Implementation Plan - Last updated: January 2025* 