#!/bin/bash

# Mintlify Documentation Validation Script
# This script validates your docs.json and documentation files locally

set -e

echo "🔍 Starting Mintlify documentation validation..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if we're in the docs directory
if [ ! -f "docs.json" ]; then
    echo -e "${RED}❌ docs.json not found. Please run this script from the docs directory.${NC}"
    exit 1
fi

echo -e "${BLUE}📋 Step 1: Validating docs.json structure...${NC}"

# Validate JSON syntax
if ! cat docs.json | python3 -m json.tool > /dev/null 2>&1; then
    echo -e "${RED}❌ docs.json has invalid JSON syntax${NC}"
    exit 1
fi

# Check required fields
if ! grep -q '"navigation"' docs.json; then
    echo -e "${RED}❌ docs.json missing required 'navigation' field${NC}"
    exit 1
fi

# Check navigation structure
if ! python3 -c "import json; config=json.load(open('docs.json')); assert isinstance(config.get('navigation', {}), dict)" 2>/dev/null; then
    echo -e "${RED}❌ navigation field must be an object, not an array${NC}"
    exit 1
fi

echo -e "${GREEN}✅ docs.json structure is valid${NC}"

echo -e "${BLUE}📋 Step 2: Checking documentation files...${NC}"

# Check if referenced files exist
python3 << 'EOF'
import json
import os
import sys

with open('docs.json', 'r') as f:
    config = json.load(f)

missing_files = []
existing_files = []

if 'navigation' in config:
    navigation = config['navigation']
    # Handle new object format with groups
    groups = navigation.get('groups', []) if isinstance(navigation, dict) else []
    
    for section in groups:
        if 'pages' in section:
            for page in section['pages']:
                name = page if isinstance(page, str) else (page.get('page') or '')
                if not name:
                    continue
                md_file = f"{name}.md"
                if not os.path.exists(md_file):
                    missing_files.append(md_file)
                else:
                    existing_files.append(md_file)

print(f"📊 Found {len(existing_files)} existing documentation files")

if missing_files:
    print("❌ Missing documentation files:")
    for file in missing_files:
        print(f"  - {file}")
    sys.exit(1)
else:
    print("✅ All referenced documentation files exist")
EOF

echo -e "${BLUE}📋 Step 3: Installing dependencies...${NC}"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}📦 Installing npm dependencies...${NC}"
    npm install
fi

echo -e "${BLUE}📋 Step 4: Running Mintlify validation...${NC}"

# Run Mintlify validation (broken links)
if command -v mint > /dev/null 2>&1; then
    echo -e "${YELLOW}🔧 Using global mint CLI...${NC}"
    mint broken-links
elif [ -f "node_modules/.bin/mint" ]; then
    echo -e "${YELLOW}🔧 Using local mint CLI...${NC}"
    npx mint broken-links
else
    echo -e "${YELLOW}⚠️  Mint CLI not found. Installing globally...${NC}"
    npm install -g mintlify
    mint broken-links
fi

echo -e "${BLUE}📋 Step 5: Testing local preview...${NC}"

# Start dev server briefly to test
echo -e "${YELLOW}🌐 Testing local preview server (5 seconds)...${NC}"

if command -v mint > /dev/null 2>&1; then
    timeout 5s mint dev --port 3333 > /dev/null 2>&1 &
elif [ -f "node_modules/.bin/mint" ]; then
    timeout 5s npx mint dev --port 3333 > /dev/null 2>&1 &
fi

MINT_PID=$!
sleep 2

# Check if server started successfully
if curl -f http://localhost:3333 > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Local preview server works correctly${NC}"
else
    echo -e "${YELLOW}⚠️  Could not verify local preview server${NC}"
fi

# Clean up
kill $MINT_PID 2>/dev/null || true

echo -e "${GREEN}🎉 All validation checks passed!${NC}"
echo -e "${BLUE}💡 To preview your docs locally, run:${NC}"
echo -e "${YELLOW}   npm run dev${NC}"
echo -e "${BLUE}💡 To build for production, run:${NC}"
echo -e "${YELLOW}   npm run build${NC}"