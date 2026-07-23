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

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}
