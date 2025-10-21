#!/bin/bash

# AgentArea Kratos JWT Token Retrieval Script
# Usage: ./get_jwt_token.sh <email> <password>

set -e

# Configuration
KRATOS_PUBLIC_URL="http://localhost:4433"
AGENTAREA_API_URL="http://localhost:8000"

# Global variables
SESSION_TOKEN=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if required tools are installed
check_dependencies() {
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl is required but not installed.${NC}"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        echo -e "${RED}Error: jq is required but not installed.${NC}"
        exit 1
    fi
}

# Show usage
usage() {
    echo "Usage: $0 <email> <password>"
    echo ""
    echo "Example:"
    echo "  $0 user@example.com mypassword"
    echo ""
    echo "This script will:"
    echo "1. Login to Kratos with provided credentials"
    echo "2. Extract JWT token from session"
    echo "3. Test the token against AgentArea API"
    echo "4. Display the JWT token for use"
}

# Login to Kratos and get session
login_to_kratos() {
    local email="$1"
    local password="$2"

    echo -e "${YELLOW}Logging in to Kratos...${NC}"

    # Step 1: Initialize login flow
    local flow_response
    flow_response=$(curl -s -X GET "${KRATOS_PUBLIC_URL}/self-service/login/api" \
        -H "Accept: application/json")

    local flow_id
    flow_id=$(echo "$flow_response" | jq -r '.id')

    if [ "$flow_id" = "null" ] || [ -z "$flow_id" ]; then
        echo -e "${RED}Failed to initialize login flow${NC}"
        echo "Response: $flow_response"
        exit 1
    fi

    echo "Flow ID: $flow_id"

    # Step 2: Submit login credentials
    local login_response
    login_response=$(curl -s -X POST "${KRATOS_PUBLIC_URL}/self-service/login?flow=${flow_id}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -d "{
            \"method\": \"password\",
            \"password_identifier\": \"$email\",
            \"password\": \"$password\"
        }")

    # Debug: uncomment the next line to see login response
    # echo "Debug - Login response: $login_response"

    # Check if login was successful
    local login_error
    login_error=$(echo "$login_response" | jq -r '.error // empty')

    if [ -n "$login_error" ]; then
        echo -e "${RED}Login failed: $login_error${NC}"
        echo "Full response: $login_response"
        exit 1
    fi

    # Extract session token from response
    SESSION_TOKEN=$(echo "$login_response" | jq -r '.session_token // empty')

    if [ -z "$SESSION_TOKEN" ] || [ "$SESSION_TOKEN" = "null" ]; then
        echo -e "${RED}No session token received${NC}"
        echo "Response: $login_response"
        exit 1
    fi

    echo "Session token: ${SESSION_TOKEN:0:20}..."
    echo -e "${GREEN}Login successful!${NC}"
}

# Get JWT token from session
get_jwt_token() {
    echo -e "${YELLOW}Retrieving JWT token...${NC}"

    # Get JWT token using session token
    # Use the same approach as the frontend: tokenize_as parameter
    local jwt_token
    
    echo -e "${YELLOW}Requesting JWT token with tokenize_as parameter...${NC}"
    local whoami_response
    whoami_response=$(curl -s -X GET "${KRATOS_PUBLIC_URL}/sessions/whoami?tokenize_as=agentarea_jwt" \
        -H "Accept: application/json" \
        -H "X-Session-Token: ${SESSION_TOKEN}")
    
    echo "Debug - Whoami response: ${whoami_response:0:200}..."
    
    # Check if we got a valid response
    if [ -z "$whoami_response" ] || [[ "$whoami_response" =~ ^[[:space:]]*$ ]]; then
        echo -e "${RED}Failed to retrieve response from Kratos${NC}"
        echo "Response: $whoami_response"
        exit 1
    fi
    
    # Extract the tokenized JWT from the response
    jwt_token=$(echo "$whoami_response" | jq -r '.tokenized // empty')
    
    if [ -z "$jwt_token" ] || [ "$jwt_token" = "null" ]; then
        echo -e "${RED}No tokenized JWT found in response${NC}"
        echo "Full response: $whoami_response"
        exit 1
    fi

    # Check if the response looks like a JWT token (has 3 parts separated by dots)
    local jwt_parts
    jwt_parts=$(echo "$jwt_token" | tr '.' ' ' | wc -w)
    if [ "$jwt_parts" -ne 3 ]; then
        echo -e "${RED}Invalid JWT token format${NC}"
        echo "Response: $jwt_token"
        exit 1
    fi

    echo -e "${GREEN}JWT token retrieved successfully!${NC}"
    echo ""
    echo -e "${GREEN}Your JWT Token:${NC}"
    echo "$jwt_token"
    echo ""

    # Test the token
    test_jwt_token "$jwt_token"
}



# Test JWT token against AgentArea API
test_jwt_token() {
    local token="$1"

    echo -e "${YELLOW}Testing JWT token against AgentArea API...${NC}"

    local test_response
    test_response=$(curl -s -X GET "${AGENTAREA_API_URL}/health" \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/json" \
        -w "\nHTTP_STATUS:%{http_code}")

    local http_status
    http_status=$(echo "$test_response" | grep "HTTP_STATUS:" | cut -d: -f2)
    local response_body
    response_body=$(echo "$test_response" | sed '/HTTP_STATUS:/d')

    if [ "$http_status" = "200" ]; then
        echo -e "${GREEN}✅ JWT token is valid and working!${NC}"
        echo ""
        echo -e "${YELLOW}Usage:${NC}"
        echo "curl -H \"Authorization: Bearer $token\" \\"
        echo "     -H \"X-Workspace-ID: default\" \\"
        echo "     ${AGENTAREA_API_URL}/v1/agents"
    else
        echo -e "${RED}❌ JWT token validation failed (HTTP $http_status)${NC}"
        echo "Response: $response_body"
    fi
}

# Cleanup
cleanup() {
    # No cleanup needed since we're using session tokens instead of cookies
    true
}

# Main function
main() {
    # Check dependencies
    check_dependencies

    # Parse arguments
    if [ $# -ne 2 ]; then
        usage
        exit 1
    fi

    local email="$1"
    local password="$2"

    # Set up cleanup on exit
    trap cleanup EXIT

    echo "AgentArea Kratos JWT Token Retrieval"
    echo "===================================="
    echo ""

    # Login and get token
    login_to_kratos "$email" "$password"
    get_jwt_token

    echo ""
    echo -e "${GREEN}Done!${NC}"
}

# Run main function
main "$@"