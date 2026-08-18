#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "$0")/.." && pwd)
installer="$root_dir/scripts/install-data-plane-agent.sh"
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'ok: %s\n' "$*"; }

release_dir="$test_dir/releases/v1.2.3"
mkdir -p "$release_dir"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "${DATA_PLANE_AGENT_TEST_AGENT_LOG:?}"\n' > "$release_dir/data-plane-agent_linux_amd64"
chmod +x "$release_dir/data-plane-agent_linux_amd64"
checksum=$(sha256sum "$release_dir/data-plane-agent_linux_amd64" | awk '{print $1}')
printf '%s  data-plane-agent_linux_amd64\n' "$checksum" > "$release_dir/SHA256SUMS"

systemctl_stub="$test_dir/systemctl"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "${DATA_PLANE_AGENT_TEST_LOG:?}"\n' > "$systemctl_stub"
chmod +x "$systemctl_stub"

run_installer() {
  DATA_PLANE_AGENT_TEST_MODE=1 \
  DATA_PLANE_AGENT_TEST_OS=Linux \
  DATA_PLANE_AGENT_TEST_ARCH=x86_64 \
  DATA_PLANE_AGENT_RELEASE_BASE_URL="file://$test_dir/releases" \
  DATA_PLANE_AGENT_BINARY_DESTINATION="$test_dir/bin/agentarea-data-plane-agent" \
  DATA_PLANE_AGENT_CONFIG_DIR="$test_dir/etc/agentarea-data-plane-agent" \
  DATA_PLANE_AGENT_STATE_DIR="$test_dir/var/lib/agentarea-data-plane-agent" \
  DATA_PLANE_AGENT_SYSTEMD_DIR="$test_dir/systemd" \
  DATA_PLANE_AGENT_SYSTEMCTL="$systemctl_stub" \
  DATA_PLANE_AGENT_TEST_LOG="$test_dir/systemctl.log" \
  DATA_PLANE_AGENT_TEST_AGENT_LOG="$test_dir/agent.log" \
  bash "$installer" "$@"
}

if run_installer >/dev/null 2>&1; then
  fail 'installer accepted a missing version'
fi
pass 'missing version is rejected'

if run_installer --version 1.2.3 >/dev/null 2>&1; then
  fail 'installer accepted a non-v release tag'
fi
pass 'non-v release tags are rejected'

run_installer --version v1.2.3
[[ -x "$test_dir/bin/agentarea-data-plane-agent" ]] || fail 'binary was not installed'
[[ -f "$test_dir/systemd/agentarea-data-plane-agent.service" ]] || fail 'systemd unit was not installed'
rg -F -- "run --config $test_dir/etc/agentarea-data-plane-agent/config.json --identity-file $test_dir/var/lib/agentarea-data-plane-agent/identity.json" "$test_dir/systemd/agentarea-data-plane-agent.service" >/dev/null \
  || fail 'systemd unit lacks explicit config and identity paths'
rg -x 'daemon-reload|enable agentarea-data-plane-agent.service' "$test_dir/systemctl.log" >/dev/null \
  || fail 'systemctl stub did not receive expected calls'
if rg -x 'start agentarea-data-plane-agent.service|restart agentarea-data-plane-agent.service' "$test_dir/systemctl.log" >/dev/null; then
  fail 'installer started an unconfigured service'
fi
pass 'verified release installs with test-only overrides'

printf '{"control_plane_url":"https://example.test","data_plane_id":"dp","connector_instance_id":"ci"}\n' \
  > "$test_dir/etc/agentarea-data-plane-agent/config.json"
run_installer --version v1.2.3
rg -F '"data_plane_id":"dp"' "$test_dir/etc/agentarea-data-plane-agent/config.json" >/dev/null \
  || fail 'rerun overwrote administrator configuration'
pass 'rerun preserves configuration'

token_source="$test_dir/one-time-enrollment.token"
printf 'test-enrollment-token\n' > "$token_source"
run_installer --version v1.2.3 \
  --control-plane-url https://control-plane.example \
  --connector-gateway-url https://connector-gateway.example \
  --data-plane-id d1f74c88-cc04-4cc7-b4e3-6054901d572a \
  --enrollment-token-file "$token_source"
[[ ! -e "$token_source" ]] || fail 'successful enrollment did not consume token source file'
[[ ! -e "$test_dir/etc/agentarea-data-plane-agent/enrollment.token" ]] || fail 'successful enrollment left copied token file behind'
rg -F 'join --config' "$test_dir/agent.log" >/dev/null \
  || fail 'installer did not join before starting the service'
rg -F 'start agentarea-data-plane-agent.service' "$test_dir/systemctl.log" >/dev/null \
  || fail 'installer did not start service after successful enrollment'
rg -F '"mcp_provider": "disabled"' "$test_dir/etc/agentarea-data-plane-agent/config.json" >/dev/null \
  || fail 'enrollment config did not disable MCP provider by default'
rg -F '"sandbox_provider": "disabled"' "$test_dir/etc/agentarea-data-plane-agent/config.json" >/dev/null \
  || fail 'enrollment config did not disable sandbox provider by default'
pass 'one-command enrollment consumes token and keeps providers disabled'

rm -f "$test_dir/var/lib/agentarea-data-plane-agent/identity.json"
token_source="$test_dir/docker-enrollment.token"
printf 'test-enrollment-token\n' > "$token_source"
PATH="$test_dir/bin:$PATH" DATA_PLANE_AGENT_TEST_DOCKER_GROUP=docker run_installer --version v1.2.3 \
  --control-plane-url https://control-plane.example \
  --connector-gateway-url https://connector-gateway.example \
  --data-plane-id d1f74c88-cc04-4cc7-b4e3-6054901d572a \
  --enrollment-token-file "$token_source" \
  --mcp-provider docker --docker-runtime true
rg -F '"mcp_provider": "docker"' "$test_dir/etc/agentarea-data-plane-agent/config.json" >/dev/null \
  || fail 'explicit Docker MCP provider was not written'
rg -F '"sandbox_provider": "disabled"' "$test_dir/etc/agentarea-data-plane-agent/config.json" >/dev/null \
  || fail 'Docker MCP enrollment enabled sandbox'
rg -F 'SupplementaryGroups=docker' "$test_dir/systemd/agentarea-data-plane-agent.service" >/dev/null \
  || fail 'Docker socket group was not granted to the service'
pass 'one-command enrollment binds an explicitly selected existing Docker runtime'

if run_installer --version v1.2.3 --control-plane-url https://control-plane.example >/dev/null 2>&1; then
  fail 'installer accepted partial enrollment configuration'
fi
pass 'partial enrollment configuration is rejected'

if rg -i 'apt(-get)? .*docker|dnf .*docker|yum .*docker|snap .*docker|install .*opensandbox|install .*k3s|iptables|ufw|firewall-cmd' "$installer" >/dev/null; then
  fail 'installer must not install a runtime or mutate host networking'
fi
pass 'installer contains no runtime or firewall mutation'

printf 'not the expected binary\n' > "$release_dir/data-plane-agent_linux_amd64"
if run_installer --version v1.2.3 >/dev/null 2>&1; then
  fail 'installer accepted a checksum mismatch'
fi
pass 'checksum mismatch is rejected'
