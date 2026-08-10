variable "bucket_name" {
  type    = string
  default = "agentarea-tfstate"
}

# Timeweb prefixes bucket names, so the name here is a request and the real
# identifier comes back as full_name. That is what the backend config needs.
variable "s3_preset_id" {
  description = "Storage preset. List them with the twc_s3_preset data source or the panel; state needs the smallest one."
  type        = number
}

variable "project_id" {
  type    = number
  default = null
}

variable "s3_user_name" {
  type    = string
  default = "agentarea-tfstate"
}
