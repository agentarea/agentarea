output "server_id" {
  value = twc_server.sandbox.id
}

# The floating address, which is what every URL and certificate is built from.
output "public_ipv4" {
  value = local.public_ip
}

output "private_ipv4" {
  description = "Address on the cluster VPC, null when the host is not attached to one."
  value       = try(twc_server.sandbox.local_network[0].ip, null)
}

# Feed these to the RU chart: mcpManager.dataPlane.url and sandboxRuntime.url.
output "dataplane_url" {
  value = local.dataplane_url
}

output "opensandbox_url" {
  value = local.sandbox_url
}

output "ssh_command" {
  value = "ssh root@${local.public_ip}"
}
