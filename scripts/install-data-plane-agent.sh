#!/usr/bin/env bash
# Install a pinned AgentArea data-plane agent release on a Linux host.
set -euo pipefail

readonly DEFAULT_RELEASE_BASE_URL="https://github.com/agentarea/agentarea/releases/download"
readonly SERVICE_NAME="agentarea-data-plane-agent.service"

version=""
control_plane_url=""
connector_gateway_url=""
data_plane_id=""
enrollment_token_file=""
enrollment_token_stdin=0
mcp_provider="disabled"
docker_runtime="docker"

usage() {
  cat <<'EOF'
Usage: install-data-plane-agent.sh --version <release-tag> [options]

Installs the public data-plane agent from the named GitHub release. A version is
required; moving references such as main and latest are deliberately rejected.

Optional enrollment options make this a complete one-command host setup:
  --control-plane-url <https-url>       AgentArea enrollment/heartbeat URL
  --connector-gateway-url <https-url>   Optional outbound command gateway URL
  --data-plane-id <uuid>                Logical data-plane ID
  --enrollment-token-file <path>        Read, use once, then remove this token file
  --enrollment-token-stdin              Read the one-time token silently from stdin
  --mcp-provider <disabled|docker>      Bind an existing host Docker runtime (default: disabled)
  --docker-runtime <path-or-name>       Existing Docker-compatible CLI (default: docker)

To enroll in the same invocation, supply --control-plane-url,
--data-plane-id, and exactly one enrollment-token option. The installer writes
the config, joins as the dedicated service user, removes the consumed token,
then enables and starts the systemd service. Providers stay disabled unless
Docker is explicitly selected; the installer never installs a runtime.

For isolated installer tests only, these environment variables may be set:
  DATA_PLANE_AGENT_RELEASE_BASE_URL  Release download base URL (default: GitHub)
  DATA_PLANE_AGENT_BINARY_DESTINATION  Installed binary path
  DATA_PLANE_AGENT_CONFIG_DIR        Configuration directory
  DATA_PLANE_AGENT_STATE_DIR         State and identity directory
  DATA_PLANE_AGENT_SYSTEMD_DIR       systemd unit directory
  DATA_PLANE_AGENT_SYSTEMCTL         systemctl executable or test stub
  DATA_PLANE_AGENT_TEST_MODE=1       Do not require root or create a host user
  DATA_PLANE_AGENT_TEST_OS/ARCH      Simulate a Linux host platform in tests
  DATA_PLANE_AGENT_TEST_DOCKER_GROUP Existing socket group used by tests
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --version)
      (($# >= 2)) || fail '--version requires a value'
      version="$2"
      shift 2
      ;;
    --control-plane-url)
      (($# >= 2)) || fail '--control-plane-url requires a value'
      control_plane_url="$2"
      shift 2
      ;;
    --connector-gateway-url)
      (($# >= 2)) || fail '--connector-gateway-url requires a value'
      connector_gateway_url="$2"
      shift 2
      ;;
    --data-plane-id)
      (($# >= 2)) || fail '--data-plane-id requires a value'
      data_plane_id="$2"
      shift 2
      ;;
    --enrollment-token-file)
      (($# >= 2)) || fail '--enrollment-token-file requires a value'
      enrollment_token_file="$2"
      shift 2
      ;;
    --enrollment-token-stdin)
      enrollment_token_stdin=1
      shift
      ;;
    --mcp-provider)
      (($# >= 2)) || fail '--mcp-provider requires a value'
      mcp_provider="$2"
      shift 2
      ;;
    --docker-runtime)
      (($# >= 2)) || fail '--docker-runtime requires a value'
      docker_runtime="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      # Do not echo unrecognised arguments: callers may accidentally pass secrets.
      fail 'unsupported installer option'
      ;;
  esac
done

[[ -n "$version" ]] || fail 'a pinned release must be supplied with --version'
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'release version must be an immutable vX.Y.Z tag'
[[ "$mcp_provider" == "disabled" || "$mcp_provider" == "docker" ]] || fail '--mcp-provider must be disabled or docker'
[[ -n "$docker_runtime" && "$docker_runtime" != *$'\n'* && "$docker_runtime" != *'"'* && "$docker_runtime" != *'\\'* ]] || fail '--docker-runtime contains unsafe JSON characters'

enroll_requested=0
if [[ -n "$control_plane_url$data_plane_id$connector_gateway_url$enrollment_token_file" || "$enrollment_token_stdin" == "1" || "$mcp_provider" != "disabled" ]]; then
  enroll_requested=1
fi

test_mode="${DATA_PLANE_AGENT_TEST_MODE:-0}"

docker_group=""
if [[ "$mcp_provider" == "docker" ]]; then
  docker_runtime_path=$(command -v "$docker_runtime" 2>/dev/null || true)
  [[ -n "$docker_runtime_path" ]] || fail 'Docker MCP provider selected but the runtime executable is not installed'
  docker_runtime="$docker_runtime_path"
  if [[ "$test_mode" == "1" && -n "${DATA_PLANE_AGENT_TEST_DOCKER_GROUP:-}" ]]; then
    docker_group="$DATA_PLANE_AGENT_TEST_DOCKER_GROUP"
  else
    docker_socket="${DATA_PLANE_AGENT_DOCKER_SOCKET:-/var/run/docker.sock}"
    [[ -S "$docker_socket" ]] || fail 'Docker MCP provider selected but its Unix socket is unavailable'
    docker_group=$(stat -c '%G' "$docker_socket")
    [[ -n "$docker_group" && "$docker_group" != "root" && "$docker_group" != "UNKNOWN" ]] \
      || fail 'Docker socket must be owned by a dedicated non-root group'
    getent group "$docker_group" >/dev/null || fail 'Docker socket group does not exist'
  fi
fi
if [[ "$enroll_requested" == "1" ]]; then
  [[ -n "$control_plane_url" ]] || fail '--control-plane-url is required when enrolling'
  [[ -n "$data_plane_id" ]] || fail '--data-plane-id is required when enrolling'
  [[ "$data_plane_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] || fail '--data-plane-id must be a UUID'
  [[ "$control_plane_url" != *$'\n'* && "$control_plane_url" != *'"'* && "$control_plane_url" != *'\\'* ]] || fail '--control-plane-url contains unsafe JSON characters'
  [[ "$connector_gateway_url" != *$'\n'* && "$connector_gateway_url" != *'"'* && "$connector_gateway_url" != *'\\'* ]] || fail '--connector-gateway-url contains unsafe JSON characters'
  if [[ "$enrollment_token_stdin" == "1" && -n "$enrollment_token_file" ]]; then
    fail 'choose only one of --enrollment-token-file or --enrollment-token-stdin'
  fi
  if [[ "$enrollment_token_stdin" == "0" && -z "$enrollment_token_file" ]]; then
    fail 'an enrollment token source is required when enrolling'
  fi
fi

if [[ "$test_mode" != "1" && "$(id -u)" -ne 0 ]]; then
  fail 'run as root (or set DATA_PLANE_AGENT_TEST_MODE=1 for the installer test harness)'
fi

host_os="$(uname -s)"
host_architecture="$(uname -m)"
if [[ "$test_mode" == "1" ]]; then
  host_os="${DATA_PLANE_AGENT_TEST_OS:-$host_os}"
  host_architecture="${DATA_PLANE_AGENT_TEST_ARCH:-$host_architecture}"
fi
[[ "$host_os" == "Linux" ]] || fail 'only Linux hosts are supported'
case "$host_architecture" in
  x86_64|amd64) architecture="amd64" ;;
  aarch64|arm64) architecture="arm64" ;;
  *) fail "unsupported Linux architecture: $host_architecture" ;;
esac

command -v curl >/dev/null 2>&1 || fail 'curl is required'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required'

release_base_url="${DATA_PLANE_AGENT_RELEASE_BASE_URL:-$DEFAULT_RELEASE_BASE_URL}"
binary_destination="${DATA_PLANE_AGENT_BINARY_DESTINATION:-/usr/local/bin/agentarea-data-plane-agent}"
config_dir="${DATA_PLANE_AGENT_CONFIG_DIR:-/etc/agentarea-data-plane-agent}"
state_dir="${DATA_PLANE_AGENT_STATE_DIR:-/var/lib/agentarea-data-plane-agent}"
systemd_dir="${DATA_PLANE_AGENT_SYSTEMD_DIR:-/etc/systemd/system}"
systemctl_command="${DATA_PLANE_AGENT_SYSTEMCTL:-systemctl}"
agent_user="${DATA_PLANE_AGENT_USER:-agentarea-data-plane-agent}"
asset="data-plane-agent_linux_${architecture}"
config_path="${config_dir}/config.json"
identity_path="${state_dir}/identity.json"
installed_token_path="${config_dir}/enrollment.token"
unit_path="${systemd_dir}/${SERVICE_NAME}"

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

printf 'Downloading data-plane agent %s for linux/%s\n' "$version" "$architecture"
curl -fsSL --retry 3 "${release_base_url%/}/${version}/${asset}" -o "$work_dir/$asset" \
  || fail 'failed to download data-plane agent release asset'
curl -fsSL --retry 3 "${release_base_url%/}/${version}/SHA256SUMS" -o "$work_dir/SHA256SUMS" \
  || fail 'failed to download SHA256SUMS'

expected_checksum=$(awk -v asset="$asset" '
  length($1) == 64 {
    filename = $NF
    sub(/^.*\//, "", filename)
    if (filename == asset) {
      print tolower($1)
      exit
    }
  }
' "$work_dir/SHA256SUMS")
[[ "$expected_checksum" =~ ^[0-9a-f]{64}$ ]] || fail 'SHA256SUMS does not contain a checksum for this platform asset'
actual_checksum=$(sha256sum "$work_dir/$asset" | awk '{print tolower($1)}')
[[ "$actual_checksum" == "$expected_checksum" ]] || fail 'checksum verification failed; refusing to install the binary'

if [[ "$test_mode" != "1" ]]; then
  if ! getent passwd "$agent_user" >/dev/null; then
    useradd --system --user-group --home-dir "$state_dir" --shell /usr/sbin/nologin "$agent_user"
  fi
fi

install -d -m 0750 "$config_dir" "$state_dir"
mkdir -p "$(dirname "$binary_destination")" "$systemd_dir"
if [[ "$test_mode" != "1" ]]; then
  chown "$agent_user:$agent_user" "$config_dir" "$state_dir"
fi

# Preserve administrator-supplied configuration and identity on ordinary reruns.
if [[ "$enroll_requested" == "1" ]]; then
  [[ ! -e "$identity_path" ]] || fail 'an identity already exists; retire or remove it before enrolling this host again'
  cat > "$config_path" <<EOF
{
  "control_plane_url": "${control_plane_url}",
  "connector_gateway_url": "${connector_gateway_url}",
  "data_plane_id": "${data_plane_id}",
  "identity_file": "${identity_path}",
  "enrollment_token_file": "${installed_token_path}",
  "mcp_provider": "${mcp_provider}",
  "sandbox_provider": "disabled",
  "docker_runtime": "${docker_runtime}",
  "docker_network": "bridge",
  "docker_name_prefix": "agentarea-mcp-",
  "docker_max_containers": 50
}
EOF
elif [[ ! -e "$config_path" ]]; then
  umask 027
  cat > "$config_path" <<'EOF'
{}
EOF
fi
chmod 0640 "$config_path"
if [[ "$test_mode" != "1" ]]; then
  chown "$agent_user:$agent_user" "$config_path"
fi

install -m 0755 "$work_dir/$asset" "$binary_destination"

supplementary_groups=""
if [[ -n "$docker_group" ]]; then
  supplementary_groups="SupplementaryGroups=${docker_group}"
fi

cat > "$unit_path" <<EOF
[Unit]
Description=AgentArea Data-Plane Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${agent_user}
Group=${agent_user}
${supplementary_groups}
ExecStart=${binary_destination} run --config ${config_path} --identity-file ${identity_path}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=${state_dir}
UMask=0077
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$unit_path"

"$systemctl_command" daemon-reload
"$systemctl_command" enable "$SERVICE_NAME"

if [[ "$enroll_requested" == "1" ]]; then
  if [[ "$enrollment_token_stdin" == "1" ]]; then
    umask 077
    IFS= read -r -s enrollment_token || true
    printf '\n' >&2
    [[ -n "$enrollment_token" ]] || fail 'enrollment token is empty'
    printf '%s\n' "$enrollment_token" > "$installed_token_path"
    unset enrollment_token
  else
    [[ -f "$enrollment_token_file" ]] || fail 'enrollment token file does not exist'
    install -m 0600 "$enrollment_token_file" "$installed_token_path"
  fi
  chmod 0600 "$installed_token_path"
  if [[ "$test_mode" != "1" ]]; then
    chown "$agent_user:$agent_user" "$installed_token_path"
    runuser --user "$agent_user" -- "$binary_destination" join --config "$config_path"
  else
    "$binary_destination" join --config "$config_path"
  fi
  rm -f -- "$installed_token_path"
  if [[ -n "$enrollment_token_file" ]]; then
    rm -f -- "$enrollment_token_file"
  fi
  "$systemctl_command" start "$SERVICE_NAME"
fi

printf 'Installed %s to %s\n' "$asset" "$binary_destination"
if [[ "$enroll_requested" == "1" ]]; then
  printf 'Enrolled and started %s; its protected identity is at %s.\n' "$SERVICE_NAME" "$identity_path"
else
  printf 'Configure %s and protected identity at %s before starting %s.\n' "$config_path" "$identity_path" "$SERVICE_NAME"
fi
