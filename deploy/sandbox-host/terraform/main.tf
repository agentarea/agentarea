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

  # The host is reached on the cluster's private network and nowhere else, so the
  # address the control plane holds is the VPC one. No public hostname, no
  # reverse proxy and no public certificate: there is no public hop to protect.
  private_ip    = one([for net in twc_server.sandbox.networks : net.ips[0].ip if net.type == "local"])
  dataplane_url = "http://${local.private_ip}:${var.dataplane_port}"
}

resource "twc_server" "sandbox" {
  name              = var.server_name
  hostname          = var.hostname
  os_id             = tonumber(data.twc_os.sandbox.id)
  availability_zone = var.availability_zone
  ssh_keys_ids      = [tonumber(twc_ssh_key.sandbox.id)]
  cloud_init        = local.cloud_init

  # No root password: the key in cloud-init is the only way in, and a password
  # Terraform generated would otherwise sit in state for the life of the host.
  is_root_password_required = false

  configuration {
    configurator_id = data.twc_configurator.sandbox.id
    cpu             = var.cpu
    ram             = var.ram_mb
    disk            = var.disk_mb
  }

  # The cluster reaches this host on the private network, and nothing else
  # reaches it at all: a machine that runs untrusted code should not be
  # addressable from the internet. That is also why there is no reverse proxy or
  # public certificate here -- the hop is inside the VPC.
  dynamic "local_network" {
    for_each = var.vpc_network_id == null ? [] : [var.vpc_network_id]

    content {
      id   = local_network.value
      mode = var.vpc_nat_mode
    }
  }
}

# The inventory is generated, so the playbook can never point at a host that
# Terraform no longer owns.
resource "local_file" "inventory" {
  filename        = "${path.module}/../inventory.ini"
  file_permission = "0644"

  content = templatefile("${path.module}/inventory.ini.tftpl", {
    private_ip = local.private_ip
    region     = "${var.location}-${var.availability_zone}"
  })
}
