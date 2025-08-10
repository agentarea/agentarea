"""Example demonstrating the usage of UserContextDep in FastAPI endpoints."""

from agentarea_common.auth import UserContextDep
from fastapi import FastAPI, HTTPException

app = FastAPI()


@app.get("/user/profile")
async def get_user_profile(user_context: UserContextDep) -> dict:
    """Get user profile using the new UserContextDep.
    
    This endpoint demonstrates how to use the UserContextDep type alias
    to automatically extract user and workspace context from JWT tokens.
    
    Args:
        user_context: Automatically injected user context from JWT token
        
    Returns:
        dict: User profile information
    """
    return {
        "user_id": user_context.user_id,
        "workspace_id": user_context.workspace_id,
        "email": user_context.email,
        "roles": user_context.roles,
        "message": f"Hello {user_context.email or user_context.user_id}!"
    }


@app.get("/workspace/info")
async def get_workspace_info(user_context: UserContextDep) -> dict:
    """Get workspace information for the current user.
    
    Args:
        user_context: Automatically injected user context from JWT token
        
    Returns:
        dict: Workspace information
    """
    return {
        "workspace_id": user_context.workspace_id,
        "user_id": user_context.user_id,
        "user_roles": user_context.roles,
        "is_admin": "admin" in user_context.roles
    }


@app.post("/workspace/resources")
async def create_workspace_resource(
    resource_data: dict,
    user_context: UserContextDep
) -> dict:
    """Create a resource in the current workspace.
    
    This demonstrates how the workspace_id and user_id from the context
    would be used to ensure proper data isolation.
    
    Args:
        resource_data: Resource data to create
        user_context: Automatically injected user context from JWT token
        
    Returns:
        dict: Created resource information
    """
    # In a real implementation, you would:
    # 1. Validate the resource_data
    # 2. Create the resource with user_context.user_id and user_context.workspace_id
    # 3. Store in database with proper workspace isolation

    return {
        "resource": resource_data,
        "created_by": user_context.user_id,
        "workspace_id": user_context.workspace_id,
        "message": "Resource created successfully"
    }


@app.get("/admin/users")
async def list_workspace_users(user_context: UserContextDep) -> dict:
    """List users in the current workspace (admin only).
    
    This demonstrates role-based access control using the context.
    
    Args:
        user_context: Automatically injected user context from JWT token
        
    Returns:
        dict: List of workspace users
        
    Raises:
        HTTPException: If user is not an admin
    """
    if "admin" not in user_context.roles:
        raise HTTPException(
            status_code=403,
            detail="Admin role required to access this endpoint"
        )

    # In a real implementation, you would query the database
    # for users in the current workspace
    return {
        "workspace_id": user_context.workspace_id,
        "users": [
            {"user_id": "user1", "email": "user1@example.com"},
            {"user_id": "user2", "email": "user2@example.com"},
        ],
        "requested_by": user_context.user_id
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
