# The Timeweb provider reads the API token from the TWC_TOKEN environment
# variable (see .envrc). Never put the token in .tfvars or version control.
provider "twc" {}
