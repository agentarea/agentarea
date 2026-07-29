output "server_id" {
  value = twc_server.sandbox.id
}

output "public_ipv4" {
  value = twc_server_ip.sandbox_ipv4.ip
}

output "ssh_command" {
  value = "ssh root@${twc_server_ip.sandbox_ipv4.ip}"
}
