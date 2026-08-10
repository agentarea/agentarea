terraform {
  required_version = ">= 1.11.0"

  required_providers {
    twc = {
      source  = "tf.timeweb.cloud/timeweb-cloud/timeweb-cloud"
      version = "~> 1.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # State describes a live machine, so it is shared and locked rather than
  # sitting on whichever laptop applied last. Values come from a backend file
  # (see backend.tfbackend.example) because they name a bucket and carry a
  # credential; the bucket itself is created by the bootstrap root next door,
  # which is the only root here that keeps its state locally.
  #
  #   terraform init -backend-config=backend.tfbackend [-migrate-state]
  backend "s3" {
    key          = "sandbox-host/terraform.tfstate"
    use_lockfile = true

    # Timeweb S3 is S3-compatible but not AWS: no STS, no account id, and paths
    # rather than virtual hosts.
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
  }
}
