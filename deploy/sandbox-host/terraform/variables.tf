variable "server_name" {
  type    = string
  default = "agentarea-sandbox-ru-1"
}

variable "hostname" {
  type    = string
  default = "agentarea-sandbox-ru-1"
}

# Timeweb server location and availability zone. Moscow = ru-3 / msk-1
# (matches the production RU environment). St. Petersburg = ru-1 / spb-3.
variable "location" {
  type    = string
  default = "ru-3"
}

variable "availability_zone" {
  type    = string
  default = "msk-1"
}

variable "preset_type" {
  type    = string
  default = "premium"
}

variable "os_name" {
  type    = string
  default = "ubuntu"
}

variable "os_version" {
  type    = string
  default = "24.04"
}

variable "cpu" {
  type    = number
  default = 4
}

variable "ram_mb" {
  type    = number
  default = 8192
}

variable "disk_mb" {
  type    = number
  default = 81920
}

variable "ssh_key_name" {
  type    = string
  default = "agentarea-sandbox-ru"
}

# No default on purpose. Ansible and every later deploy reach the host with this
# key, so a default would hand the box a key whoever runs this may not hold, and
# the mistake only surfaces once the machine is already unreachable.
variable "ssh_public_key_path" {
  type = string
}

# The cluster VPC this host joins. Sourced from the RU cluster stack
# (agentarea-hq/infra .../timeweb-ru, twc_vpc.cluster). Pass null explicitly to
# keep the host off the private network -- there is no default, because a host
# that silently ends up outside the VPC looks identical to one inside it.
variable "vpc_network_id" {
  type = string
}

# Left null on purpose: Timeweb answers the separate "set local network mode"
# call with HTTP 500 for this account, and the mode it assigns on attachment is
# already egress-only, which is what a host running untrusted code should have.
# Set it explicitly only if that call starts working and ingress is wanted.
variable "vpc_nat_mode" {
  type    = string
  default = null

  validation {
    condition     = var.vpc_nat_mode == null || contains(["snat", "dnat_and_snat"], var.vpc_nat_mode)
    error_message = "vpc_nat_mode must be snat, dnat_and_snat, or null."
  }
}

# Where the data plane listens. It binds the private address, so this port is
# reachable from the cluster and from nowhere else.
variable "dataplane_port" {
  type    = number
  default = 8090
}
