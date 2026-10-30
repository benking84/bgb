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
