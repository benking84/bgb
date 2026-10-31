variable "project_id" {
  type        = string
  description = "Existing GCP project id. Terraform does not create the project."
}

variable "region" {
  type    = string
  default = "australia-southeast1"
}

variable "firestore_location" {
  type        = string
  description = "Firestore location. The (default) database can be created only once per project."
  default     = "australia-southeast1"
}

variable "bucket_name" {
  type = string
}

variable "image" {
  type        = string
  description = "Bootstrap Cloud Run image. Cloud Deploy owns the running image after the first release (DEP-D1), so this is used only when the service and job are first created."
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "allow_unauthenticated" {
  type    = bool
  default = false
}

variable "kms_key_name" {
  type        = string
  description = "Optional Cloud KMS key for the backup bucket, as projects/PROJECT/locations/LOCATION/keyRings/RING/cryptoKeys/KEY. Empty uses Google-managed encryption."
  default     = ""
}

variable "backup_project_id" {
  type        = string
  description = "Optional separate project for the backup bucket, so the app project's owners and a compromised app cannot reach it. Empty uses project_id."
  default     = ""
}

variable "object_retention_days" {
  type        = number
  description = "Bucket retention period. No object can be deleted or replaced until it is this old. 0 turns it off."
  default     = 30
}

variable "lock_retention" {
  type        = bool
  description = "Lock the bucket retention policy. Irreversible: the period can then never be shortened or removed, and the bucket and project cannot be deleted until every object is old enough."
  default     = false
}

variable "soft_delete_days" {
  type        = number
  description = "How long deleted objects stay restorable, 7 to 90 days."
  default     = 90
}

variable "job_timeout_hours" {
  type        = number
  description = "Backup job task timeout. Cloud Run allows up to 168 hours."
  default     = 24
}

variable "job_max_retries" {
  type        = number
  description = "Retries for a failed backup task. Each retry resumes from the last checkpoint."
  default     = 3
}

variable "deploy_targets" {
  type = map(object({
    project_id       = optional(string)
    region           = optional(string)
    require_approval = optional(bool, false)
    parameters       = optional(map(string), {})
  }))
  description = "Cloud Deploy targets by id. project_id and region default to var.project_id and var.region. parameters override the base deploy parameters for that target."
  default     = { prod = {} }
}

variable "deploy_stage_order" {
  type        = list(string)
  description = "Target ids in promotion order. Each must be a key of deploy_targets."
  default     = ["prod"]
}

variable "iap_audience" {
  type        = string
  description = "IAP audience the service validates (BGB_IAP_AUDIENCE). Empty until IAP is set up (Story 5.1)."
  default     = ""
}

variable "github_connection_name" {
  type        = string
  description = "Name of the 2nd gen Cloud Build GitHub connection. Authorised once in the console, then imported (see CI-CD-SETUP.md)."
  default     = "bgb-github"
}

variable "github_repository_uri" {
  type        = string
  description = "GitHub repository that triggers builds."
  default     = "https://github.com/AviatoConsulting/bgb.git"
}
