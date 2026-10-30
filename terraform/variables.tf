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
  description = "Cloud Run image, for example REGION-docker.pkg.dev/PROJECT/bgb/bgb:latest"
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
