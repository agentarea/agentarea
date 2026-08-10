# Everything the backend config of the other roots needs. The bucket carries its
# own credentials, so there is no separate S3 user to create and revoke.
output "bucket" {
  description = "Real bucket identifier, including the prefix Timeweb adds."
  value       = twc_s3_bucket.tfstate.full_name
}

output "endpoint" {
  value = "https://${twc_s3_bucket.tfstate.hostname}"
}

output "access_key" {
  value     = twc_s3_bucket.tfstate.access_key
  sensitive = true
}

output "secret_key" {
  value     = twc_s3_bucket.tfstate.secret_key
  sensitive = true
}

output "preset_id" {
  value = var.s3_preset_id
}
