variable "project_id" {
  type        = string
  description = "Existing GCP project id. Terraform does not create the project."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "firestore_location" {
  type        = string
  description = "Firestore location. The (default) database can be created only once per project."
  default     = "nam5"
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
