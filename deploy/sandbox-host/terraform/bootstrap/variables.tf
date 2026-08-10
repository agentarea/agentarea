variable "bucket_name" {
  type    = string
  default = "agentarea-tfstate"
}

# Timeweb prefixes bucket names, so the name here is a request and the real
# identifier comes back as full_name. That is what the backend config needs.
# The storage preset, pinned by id.
#
# The twc_s3_preset data source cannot be used: it reads the whole preset list
# and decodes prices as integers, and Timeweb prices its cold tier at 1.1, so the
# lookup fails for every preset. List them instead with:
#
#   curl -sH "Authorization: Bearer $TWC_TOKEN" \
#     https://api.timeweb.cloud/api/v1/presets/storages
#
# State is kilobytes, so the smallest hot preset is the right one: 4611 is
# "Premium 1GB" in ru-1 at 1 RUB/month.
variable "s3_preset_id" {
  type = number
}

variable "project_id" {
  type    = number
  default = null
}
