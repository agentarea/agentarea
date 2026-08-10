# State belongs in a shared, locked bucket rather than on whichever machine
# applied last. The bucket is not there yet: Timeweb answers bucket creation with
# HTTP 500 for this account (both through the provider and through
# POST /api/v1/storages/buckets), so S3 has to be repaired or enabled on the
# account first. The bootstrap root next door creates the bucket the moment it
# can.
#
# Until then state is local to the machine that applies, which is the known gap.
# To switch, once `cd bootstrap && terraform apply` succeeds:
#
#   cp backend.tfbackend.example backend.tfbackend   # fill from bootstrap outputs
#   export AWS_ACCESS_KEY_ID=$(cd bootstrap && terraform output -raw access_key)
#   export AWS_SECRET_ACCESS_KEY=$(cd bootstrap && terraform output -raw secret_key)
#   terraform init -backend-config=backend.tfbackend -migrate-state
#
# terraform {
#   backend "s3" {
#     key          = "sandbox-host/terraform.tfstate"
#     use_lockfile = true
#
#     use_path_style              = true
#     skip_credentials_validation = true
#     skip_region_validation      = true
#     skip_requesting_account_id  = true
#     skip_metadata_api_check     = true
#   }
# }
