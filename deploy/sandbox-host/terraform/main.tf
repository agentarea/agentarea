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

  # Every URL the control plane holds for this host is derived from its address,
  # so the address has to be the thing that survives a rebuild.
  public_ip     = twc_floating_ip.sandbox.ip
  dashed_ip     = replace(local.public_ip, ".", "-")
  dataplane_url = "https://mcp-dp.${local.dashed_ip}.sslip.io"
  sandbox_url   = "https://opensandbox.${local.dashed_ip}.sslip.io"
}

# A server-bound address dies with the server, which made every rebuild rewrite
# the data-plane URL, the OpenSandbox URL and both certificates. A floating IP is
# its own resource with its own lifecycle, so the host becomes replaceable
# without the control plane noticing.
resource "twc_floating_ip" "sandbox" {
  availability_zone = var.availability_zone
  comment           = "Stable public address for ${var.server_name}"
}

resource "twc_server" "sandbox" {
  name              = var.server_name
  hostname          = var.hostname
  os_id             = tonumber(data.twc_os.sandbox.id)
  availability_zone = var.availability_zone
  ssh_keys_ids      = [tonumber(twc_ssh_key.sandbox.id)]
  cloud_init        = local.cloud_init
  floating_ip_id    = twc_floating_ip.sandbox.id

  # No root password: the key in cloud-init is the only way in, and a password
  # Terraform generated would otherwise sit in state for the life of the host.
  is_root_password_required = false

  configuration {
    configurator_id = data.twc_configurator.sandbox.id
    cpu             = var.cpu
    ram             = var.ram_mb
    disk            = var.disk_mb
  }

  # The host answers the cluster over the public hop, but it also belongs on the
  # cluster's private network: an in-region registry or mirror is then reachable
  # without putting registry credentials on a machine that runs untrusted code.
  # Egress-only NAT, because ingress arrives on the floating address.
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
    public_ip = local.public_ip
    region    = "${var.location}-${var.availability_zone}"
  })
}
