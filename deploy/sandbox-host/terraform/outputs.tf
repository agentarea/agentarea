output "server_id" {
  value = twc_server.sandbox.id
}

# The only address anything is meant to use: the host has no public entry point.
output "private_ipv4" {
  value = local.private_ip
}

# Feed this to the RU chart as mcpManager.dataPlane.url.
output "dataplane_url" {
  value = local.dataplane_url
}

# Reaching a host with no public address goes through the cluster that is on its
# network, so the jump is part of the contract rather than a local trick.
output "ssh_command" {
  value = "ssh -o ProxyCommand='kubectl -n agentarea exec -i jump -- socat - TCP:%h:%p' root@${local.private_ip}"
}
