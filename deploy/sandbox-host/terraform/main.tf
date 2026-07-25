# A single dedicated sandbox host. Deliberately isolated: its own local state,
# no dependency on and no shared state with the production Kubernetes clusters.
# Host configuration (Docker + gVisor + executor) is done by the Ansible role in
# ../ against the IP this outputs — Terraform only creates the box.

data "twc_configurator" "sandbox" {
  location    = var.location
  preset_type = var.preset_type
}

data "twc_os" "sandbox" {
  name    = var.os_name
  version = var.os_version
}

resource "twc_ssh_key" "sandbox" {
  name = var.ssh_key_name
  body = file(pathexpand(var.ssh_public_key_path))
}

locals {
  ssh_pubkey = trimspace(file(pathexpand(var.ssh_public_key_path)))

  # Minimal cloud-init: guarantee key-based root SSH (Timeweb's ssh_keys_ids
  # injection for root is unreliable on a bare image) and ensure python3 so the
  # Ansible role can run. All real configuration is done by Ansible afterwards.
  cloud_init = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_pubkey = local.ssh_pubkey
  })
}

resource "twc_server" "sandbox" {
  name              = var.server_name
  hostname          = var.hostname
  os_id             = tonumber(data.twc_os.sandbox.id)
  availability_zone = var.availability_zone
  ssh_keys_ids      = [tonumber(twc_ssh_key.sandbox.id)]
  cloud_init        = local.cloud_init

  configuration {
    configurator_id = data.twc_configurator.sandbox.id
    cpu             = var.cpu
    ram             = var.ram_mb
    disk            = var.disk_mb
  }
}

resource "twc_server_ip" "sandbox_ipv4" {
  source_server_id = tonumber(twc_server.sandbox.id)
  type             = "ipv4"
}
