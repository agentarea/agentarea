#!/usr/bin/env bash
# Reject public references to AgentArea-hosted sandbox infrastructure.

set -euo pipefail

cd "$(dirname "$0")/.."

failed=0

# A tracked path is itself a policy violation. `git ls-files` deliberately does
# not enumerate ignored operational inventory, state, or kubeconfig files.
while IFS= read -r path; do
  printf '%s\n' "$path"
  failed=1
done < <(git ls-files -- deploy/sandbox-host)

# Restrict content checks to public deployment and customer-documentation
# surfaces. In particular, legacy MCP manager code remains until the later
# transport-removal change.
scan_paths=()
while IFS= read -r -d '' path; do
  case "$path" in
    docs/*|charts/*|deploy/*|docker-compose*.yml|docker-compose*.yaml|compose*.yml|compose*.yaml)
      scan_paths+=("$path")
      ;;
  esac
done < <(git ls-files -z)

check_marker() {
  local marker exit_code
  marker=$1

  if git grep -n -I -F -e "$marker" -- "${scan_paths[@]}"; then
    failed=1
    return
  else
    exit_code=$?
  fi

  if [[ $exit_code -ne 1 ]]; then
    exit "$exit_code"
  fi
}

check_marker 'deploy/sandbox-host'
check_marker 'sandbox_mcp_dataplane_'
check_marker 'opensandbox.72-56-235-217.sslip.io'
check_marker '194.87.187.68/32'
check_marker 'agentarea-sandbox-ru-1'
check_marker 'twc_server'

exit "$failed"
