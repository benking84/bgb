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
