output "service_url" {
  value = google_cloud_run_v2_service.ui.uri
}

output "backup_job" {
  value = local.backup_job_name
}

output "bucket" {
  value = google_storage_bucket.backups.name
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "ui_service_account" {
  value = google_service_account.ui.email
}

output "delegate_service_account" {
  description = "Put this in Settings → service account email, and authorize its client id for domain-wide delegation."
  value       = google_service_account.delegate.email
}

output "delegate_client_id" {
  value = google_service_account.delegate.unique_id
}

output "artifact_registry" {
  description = "Image repository path. Images are pushed as this path plus /bgb:TAG."
  value       = "${google_artifact_registry_repository.bgb.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.bgb.repository_id}"
}

output "cloudbuild_service_account" {
  value = google_service_account.cloudbuild.email
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}

output "service_name" {
  value = google_cloud_run_v2_service.ui.name
}

output "backup_job_id" {
  value = google_cloud_run_v2_job.backup.id
}

output "github_connection" {
  value = google_cloudbuildv2_connection.github.name
}

output "pr_trigger" {
  value = google_cloudbuild_trigger.pr.name
}

output "main_trigger" {
  value = google_cloudbuild_trigger.main.name
}
