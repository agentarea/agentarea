#!/bin/bash

# AgentArea CLI Test Script
# This script tests all CLI commands to verify the workspace imports are working correctly

set -e  # Exit on any error

echo "🧪 Testing AgentArea CLI after workspace import refactoring..."
echo "================================================"

# Change to the core directory
cd "$(dirname "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to run a command and check if it succeeds
test_command() {
    local cmd="$1"
    local description="$2"
    
    echo -e "\n${YELLOW}Testing: $description${NC}"
    echo "Command: $cmd"
    
    if eval "$cmd" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}"
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        echo "Error output:"
        eval "$cmd" 2>&1 || true
        return 1
    fi
}

# Function to run a command and show output
test_command_with_output() {
    local cmd="$1"
    local description="$2"
    
    echo -e "\n${YELLOW}Testing: $description${NC}"
    echo "Command: $cmd"
    
    if output=$(eval "$cmd" 2>&1); then
        echo -e "${GREEN}✅ PASS${NC}"
        echo "Output:"
        echo "$output" | head -10  # Show first 10 lines
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        echo "Error output:"
        echo "$output"
        return 1
    fi
}

# Test counter
total_tests=0
passed_tests=0

# Test basic CLI import
echo -e "\n${YELLOW}=== Testing Basic CLI Import ===${NC}"
total_tests=$((total_tests + 1))
if test_command "python -c 'import agentarea_cli.main; print(\"CLI imports working\")'"; then
    passed_tests=$((passed_tests + 1))
fi

# Test main CLI help
echo -e "\n${YELLOW}=== Testing Main CLI Help ===${NC}"
total_tests=$((total_tests + 1))
if test_command_with_output "python -m agentarea_cli.main --help" "Main CLI help"; then
    passed_tests=$((passed_tests + 1))
fi

# Test authentication commands
echo -e "\n${YELLOW}=== Testing Authentication Commands ===${NC}"
auth_commands=(
    "python -m agentarea_cli.main auth --help"
    "python -m agentarea_cli.main auth config --help"
    "python -m agentarea_cli.main auth login --help"
    "python -m agentarea_cli.main auth logout --help"
    "python -m agentarea_cli.main auth status --help"
)

for cmd in "${auth_commands[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "Auth command: $(echo $cmd | cut -d' ' -f4-)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Test agent commands
echo -e "\n${YELLOW}=== Testing Agent Commands ===${NC}"
agent_commands=(
    "python -m agentarea_cli.main agent --help"
    "python -m agentarea_cli.main agent create --help"
    "python -m agentarea_cli.main agent list --help"
    "python -m agentarea_cli.main agent show --help"
    "python -m agentarea_cli.main agent update --help"
    "python -m agentarea_cli.main agent delete --help"
)

for cmd in "${agent_commands[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "Agent command: $(echo $cmd | cut -d' ' -f4-)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Test LLM commands
echo -e "\n${YELLOW}=== Testing LLM Commands ===${NC}"
llm_commands=(
    "python -m agentarea_cli.main llm --help"
    "python -m agentarea_cli.main llm create --help"
    "python -m agentarea_cli.main llm list --help"
    "python -m agentarea_cli.main llm show --help"
    "python -m agentarea_cli.main llm update --help"
    "python -m agentarea_cli.main llm delete --help"
    "python -m agentarea_cli.main llm providers --help"
    "python -m agentarea_cli.main llm test --help"
)

for cmd in "${llm_commands[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "LLM command: $(echo $cmd | cut -d' ' -f4-)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Test chat commands
echo -e "\n${YELLOW}=== Testing Chat Commands ===${NC}"
chat_commands=(
    "python -m agentarea_cli.main chat --help"
    "python -m agentarea_cli.main chat agents --help"
    "python -m agentarea_cli.main chat send --help"
    "python -m agentarea_cli.main chat history --help"
    "python -m agentarea_cli.main chat clear --help"
)

for cmd in "${chat_commands[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "Chat command: $(echo $cmd | cut -d' ' -f4-)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Test system commands
echo -e "\n${YELLOW}=== Testing System Commands ===${NC}"
system_commands=(
    "python -m agentarea_cli.main system --help"
    "python -m agentarea_cli.main system info --help"
    "python -m agentarea_cli.main system status --help"
    "python -m agentarea_cli.main system components --help"
    "python -m agentarea_cli.main system logs --help"
    "python -m agentarea_cli.main system metrics --help"
    "python -m agentarea_cli.main system restart --help"
)

for cmd in "${system_commands[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "System command: $(echo $cmd | cut -d' ' -f4-)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Test workspace imports specifically
echo -e "\n${YELLOW}=== Testing Workspace Imports ===${NC}"
import_tests=(
    "python -c 'from agentarea_cli.client import AgentAreaClient; print(\"Client import OK\")'"
    "python -c 'from agentarea_cli.config import Config, AuthConfig; print(\"Config import OK\")'"
    "python -c 'from agentarea_cli.exceptions import AgentAreaError; print(\"Exceptions import OK\")'"
    "python -c 'from agentarea_cli.utils import format_table; print(\"Utils import OK\")'"
    "python -c 'from agentarea_common.auth import UserContext; print(\"Common auth import OK\")'"
    "python -c 'from agentarea_common.exceptions import WorkspaceError; print(\"Common exceptions import OK\")'"
)

for cmd in "${import_tests[@]}"; do
    total_tests=$((total_tests + 1))
    if test_command "$cmd" "Import test: $(echo $cmd | cut -d\"'\" -f2 | cut -d';' -f1)"; then
        passed_tests=$((passed_tests + 1))
    fi
done

# Summary
echo -e "\n${YELLOW}================================================${NC}"
echo -e "${YELLOW}Test Summary${NC}"
echo -e "Total tests: $total_tests"
echo -e "Passed: ${GREEN}$passed_tests${NC}"
echo -e "Failed: ${RED}$((total_tests - passed_tests))${NC}"

if [ $passed_tests -eq $total_tests ]; then
    echo -e "\n${GREEN}🎉 All tests passed! CLI workspace imports are working correctly.${NC}"
    exit 0
else
    echo -e "\n${RED}❌ Some tests failed. Please check the output above.${NC}"
    exit 1
fi