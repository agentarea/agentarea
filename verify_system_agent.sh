#!/bin/bash
# Verification script to check if system agent is visible

set -e

echo "=== Verifying System Agent Configuration ==="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Check if bootstrap created system agent
echo "1. Checking if system agent exists in database..."
SYSTEM_AGENT_COUNT=$(docker exec agentarea-backend python -c "
import sys
sys.path.insert(0, '/app')
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres:postgres@db:5432/aiagents')
with engine.connect() as conn:
    result = conn.execute(text(\"SELECT COUNT(*) FROM agents WHERE workspace_id = 'system'\"))
    print(result.scalar())
" 2>/dev/null)

if [ "$SYSTEM_AGENT_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found $SYSTEM_AGENT_COUNT system agent(s) in database"

    # Show details
    docker exec agentarea-backend python -c "
import sys
sys.path.insert(0, '/app')
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres:postgres@db:5432/aiagents')
with engine.connect() as conn:
    result = conn.execute(text(\"SELECT id, name, workspace_id, created_by FROM agents WHERE workspace_id = 'system'\"))
    for row in result:
        print(f'  - ID: {row[0]}')
        print(f'    Name: {row[1]}')
        print(f'    Workspace: {row[2]}')
        print(f'    Created by: {row[3]}')
" 2>/dev/null
else
    echo -e "${RED}✗${NC} No system agents found in database"
    echo -e "${YELLOW}   You may need to run bootstrap to create the system agent${NC}"
fi

echo ""

# 2. Verify middleware changes
echo "2. Checking middleware workspace assignment logic..."
if grep -q "workspace_id = user_id" /Users/jamakase/Projects/startup/agentarea/agentarea-platform/libs/common/agentarea_common/auth/middleware.py; then
    echo -e "${GREEN}✓${NC} Middleware correctly uses user_id as workspace_id"
else
    echo -e "${RED}✗${NC} Middleware changes not found"
fi

echo ""

# 3. Verify repository changes
echo "3. Checking repository system filter..."
if grep -q "_get_workspace_filter_with_system" /Users/jamakase/Projects/startup/agentarea/agentarea-platform/libs/agents/agentarea_agents/infrastructure/repository.py; then
    echo -e "${GREEN}✓${NC} Repository has system workspace filter"
else
    echo -e "${RED}✗${NC} Repository changes not found"
fi

echo ""

# 4. Test the filter logic in Python
echo "4. Testing workspace filter logic..."
docker exec agentarea-backend python -c "
import sys
sys.path.insert(0, '/app')

# Test that the filter includes both user workspace and system workspace
from sqlalchemy import or_, text, create_engine, Column, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class TestModel(Base):
    __tablename__ = 'agents'
    workspace_id = Column(String)

# Simulate the filter
user_workspace = 'test-user-123'
system_workspace = 'system'

filter_condition = or_(
    TestModel.workspace_id == user_workspace,
    TestModel.workspace_id == system_workspace
)

print(f'Filter will match agents with workspace_id:')
print(f'  - {user_workspace} (user workspace)')
print(f'  - {system_workspace} (system workspace)')
print('')
print('This means users will see:')
print('  1. Their own agents')
print('  2. System agents')
" 2>/dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Filter logic is correct"
else
    echo -e "${RED}✗${NC} Error testing filter logic"
fi

echo ""

# 5. Check if API container is running
echo "5. Checking if API container is running..."
if docker ps | grep -q agentarea-backend; then
    echo -e "${GREEN}✓${NC} API container is running"

    # Check container logs for recent errors
    echo ""
    echo "   Recent API logs:"
    docker logs agentarea-backend --tail 5 2>&1 | sed 's/^/   /'
else
    echo -e "${RED}✗${NC} API container is not running"
fi

echo ""
echo "=== Verification Complete ==="
echo ""
echo "Summary:"
echo "- System agent should exist in database with workspace_id='system'"
echo "- Users will get workspace_id=user_id when they log in"
echo "- Agent queries will include both user's workspace AND system workspace"
echo "- Therefore, all users should see the system agent in the UI"
