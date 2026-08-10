# Everything the backend config of the other roots needs.
output "bucket" {
  description = "Real bucket identifier, including the prefix Timeweb adds."
  value       = twc_s3_bucket.tfstate.full_name
}

output "endpoint" {
  value = "https://${twc_s3_bucket.tfstate.hostname}"
}

output "access_key" {
  value     = twc_s3_user.tfstate.access_key
  sensitive = true
}

output "secret_key" {
  value     = twc_s3_user.tfstate.secret_key
  sensitive = true
}
