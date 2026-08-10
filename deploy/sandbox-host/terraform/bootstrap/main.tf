# Bootstrap: the bucket that holds the state of every other root here.
#
# This is the one root that keeps its state locally, because it cannot store
# state in the bucket it is creating. It manages two resources and is applied
# once, so a lost local state is recoverable by importing them; the state that
# actually describes running infrastructure lives in the bucket.

resource "twc_s3_bucket" "tfstate" {
  name       = var.bucket_name
  type       = "private"
  preset_id  = var.s3_preset_id
  project_id = var.project_id

  # State is small and rewritten constantly; growing into a bigger preset by
  # surprise is worse than failing a write, which is loud and recoverable.
  is_allow_auto_upgrade = false
}
