# Subdomain Proxy Plan for A2A Agents 🌐

## 🎯 Goal: Agent-Specific Subdomains

Transform from:
```
domain.com/v1/agents/123/.well-known/agent.json
domain.com/v1/agents/456/.well-known/agent.json
```

To:
```
agent-123.domain.com/.well-known/agent.json
agent-456.domain.com/.well-known/agent.json
```

## 🏗️ Current Implementation

### ✅ What We Have Now
1. **Main domain agent**: `domain.com/.well-known/agent.json`
2. **Agent-specific well-known**: `/v1/agents/{id}/.well-known/agent.json`
3. **Agent-specific RPC**: `/v1/agents/{id}/rpc`
4. **Subdomain detection**: Already implemented in global well-known

### 📋 URL Structure
```
# Main domain (primary agent)
domain.com/.well-known/agent.json           → Primary agent
domain.com/v1/agents/{id}/rpc                → Primary agent communication

# Agent-specific endpoints  
domain.com/v1/agents/{id}/.well-known/agent.json  → Any agent discovery
domain.com/v1/agents/{id}/rpc                      → Any agent communication
domain.com/v1/agents/{id}/stream                   → Any agent streaming

# Future subdomain support
agent-{id}.domain.com/.well-known/agent.json → Proxy to /v1/agents/{id}/.well-known/
agent-{id}.domain.com/rpc                    → Proxy to /v1/agents/{id}/rpc
```

## 🔧 Implementation Options

### Option 1: Nginx/Reverse Proxy (Recommended)
```nginx
# Nginx configuration
server {
    server_name ~^agent-(?<agent_id>[a-f0-9-]+)\.domain\.com$;
    
    location /.well-known/ {
        proxy_pass http://backend/v1/agents/$agent_id/.well-known/;
    }
    
    location /rpc {
        proxy_pass http://backend/v1/agents/$agent_id/rpc;
    }
    
    location /stream {
        proxy_pass http://backend/v1/agents/$agent_id/stream;
    }
    
    location /card {
        proxy_pass http://backend/v1/agents/$agent_id/card;
    }
}

# Main domain
server {
    server_name domain.com;
    
    location / {
        proxy_pass http://backend/;
    }
}
```

### Option 2: FastAPI Subdomain Routing
```python
from fastapi import FastAPI, Request
import re

app = FastAPI()

@app.middleware("http")
async def subdomain_proxy_middleware(request: Request, call_next):
    host = request.headers.get("host", "").lower()
    
    # Check for agent subdomain pattern
    match = re.match(r'^agent-([a-f0-9-]+)\.', host)
    if match:
        agent_id = match.group(1)
        
        # Rewrite path for agent-specific endpoints
        path = request.url.path
        if path.startswith("/.well-known/"):
            new_path = f"/v1/agents/{agent_id}/.well-known{path[12:]}"
        elif path == "/rpc":
            new_path = f"/v1/agents/{agent_id}/rpc"
        elif path == "/stream":
            new_path = f"/v1/agents/{agent_id}/stream"
        elif path == "/card":
            new_path = f"/v1/agents/{agent_id}/card"
        else:
            new_path = path
            
        # Update request path
        request.scope["path"] = new_path
        request.scope["raw_path"] = new_path.encode()
    
    response = await call_next(request)
    return response
```

### Option 3: DNS Wildcard + Load Balancer
```yaml
# Kubernetes/Docker Compose approach
services:
  agentarea-api:
    # Main API service
    
  agent-proxy:
    # Proxy service for subdomain routing
    environment:
      - AGENT_API_URL=http://agentarea-api:8000
    
# DNS Configuration
*.domain.com → Load Balancer → Agent Proxy Service
```

## 🚀 Migration Steps

### Phase 1: Current State (✅ Done)
```
✅ Main domain agent: domain.com/.well-known/agent.json
✅ Agent endpoints: /v1/agents/{id}/.well-known/agent.json
✅ Subdomain detection in code
```

### Phase 2: Proxy Setup
```
1. Setup wildcard DNS: *.domain.com
2. Configure reverse proxy (Nginx recommended)
3. Test subdomain routing
```

### Phase 3: Agent Registration
```
1. Agents register their preferred subdomain
2. Update agent cards with subdomain URLs
3. Automatic subdomain assignment
```

### Phase 4: Full Migration
```
1. All agents available on subdomains
2. Main domain keeps primary agent
3. Backward compatibility maintained
```

## 🧪 Testing Plan

### Manual Testing
```bash
# Current (works now)
curl https://domain.com/.well-known/agent.json
curl https://domain.com/v1/agents/123/.well-known/agent.json

# Future (after proxy setup)
curl https://agent-123.domain.com/.well-known/agent.json
curl https://agent-456.domain.com/.well-known/agent.json

# Communication
curl -X POST https://agent-123.domain.com/rpc -d '{...}'
```

### Automated Testing
```python
async def test_subdomain_proxy():
    # Test main domain
    response = await client.get("https://domain.com/.well-known/agent.json")
    assert response.status_code == 200
    
    # Test agent subdomain (after proxy setup)
    response = await client.get("https://agent-123.domain.com/.well-known/agent.json")
    assert response.status_code == 200
    
    # Verify it's the same agent
    agent_direct = await client.get("https://domain.com/v1/agents/123/.well-known/agent.json")
    assert response.json() == agent_direct.json()
```

## 🔒 Security Considerations

### DNS Security
- Wildcard DNS properly configured
- Prevent subdomain takeover
- Rate limiting per subdomain

### Proxy Security
- Validate agent ID format (UUID)
- Prevent path traversal
- Proper error handling

### Agent Isolation
- Each subdomain isolated to its agent
- No cross-agent access
- Proper authentication per agent

## 📋 Deployment Checklist

### DNS Setup
- [ ] Configure wildcard DNS (*.domain.com)
- [ ] Verify DNS propagation
- [ ] Setup SSL certificates for wildcards

### Proxy Configuration
- [ ] Configure Nginx/proxy rules
- [ ] Test subdomain routing
- [ ] Setup health checks

### Agent Configuration
- [ ] Update agent cards with subdomain URLs
- [ ] Test all agent endpoints
- [ ] Verify backward compatibility

### Monitoring
- [ ] Setup subdomain monitoring
- [ ] Configure alerts for proxy errors
- [ ] Monitor agent-specific metrics

## 🌟 Benefits

### A2A Compliance
- ✅ **Standard compliant**: Each agent has its own domain
- ✅ **Proper isolation**: Agent-specific endpoints
- ✅ **Scalable**: Easy to add new agents

### User Experience
- 🎯 **Clear agent identity**: agent-name.domain.com
- 🔗 **Easy sharing**: Direct agent URLs
- 📱 **Mobile friendly**: Short, memorable URLs

### Operations
- 📊 **Per-agent metrics**: Easy monitoring
- 🔧 **Agent-specific config**: Independent settings
- 🚀 **Horizontal scaling**: Agent-specific deployments

---

**Next Steps**: Choose proxy option (recommend Nginx) and setup wildcard DNS! 🚀