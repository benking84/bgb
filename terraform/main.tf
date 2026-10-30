terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  backup_job_id   = "bgb-backup"
  backup_job_name = "projects/${var.project_id}/locations/${var.region}/jobs/${local.backup_job_id}"
  use_cmek        = var.kms_key_name != ""
  services = concat([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
  ], var.kms_key_name == "" ? [] : ["cloudkms.googleapis.com"])
}

resource "google_project_service" "required" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.required]
}

data "google_storage_project_service_account" "gcs" {
  count      = local.use_cmek ? 1 : 0
  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key_iam_member" "gcs_agent" {
  count         = local.use_cmek ? 1 : 0
  crypto_key_id = var.kms_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs[0].email_address}"
}

resource "google_kms_crypto_key_iam_member" "runtime" {
  count         = local.use_cmek ? 1 : 0
  crypto_key_id = var.kms_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "backups" {
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  dynamic "encryption" {
    for_each = local.use_cmek ? [var.kms_key_name] : []
    content {
      default_kms_key_name = encryption.value
    }
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.gcs_agent,
    google_kms_crypto_key_iam_member.runtime,
  ]
}

resource "google_service_account" "runtime" {
  account_id   = "bgb-run"
  display_name = "bgb Cloud Run runtime"
}

resource "google_service_account" "scheduler" {
  account_id   = "bgb-scheduler"
  display_name = "bgb Cloud Scheduler"
}

resource "google_storage_bucket_iam_member" "runtime_objects" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Lets the runtime account sign Workspace-delegation JWTs without a JSON key.
resource "google_service_account_iam_member" "runtime_signs_itself" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret" "workspace_sa" {
  secret_id = "bgb-workspace-sa"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "workspace_sa" {
  secret_id = google_secret_manager_secret.workspace_sa.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "ui" {
  name     = "bgb"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "3600s"
    max_instance_request_concurrency = 80
    containers {
      image = var.image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
      env {
        name  = "BGB_USE_GCP"
        value = "1"
      }
      env {
        name  = "BGB_INDEX"
        value = "firestore"
      }
      env {
        name  = "BGB_VOLUMES"
        value = "gcs"
      }
      env {
        name  = "BGB_GCS_BUCKET"
        value = google_storage_bucket.backups.name
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BGB_CLOUD_RUN_JOB"
        value = local.backup_job_name
      }
    }
  }
  depends_on = [google_project_service.required, google_cloud_run_v2_job.backup]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  name     = google_cloud_run_v2_service.ui.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "backup" {
  name     = local.backup_job_id
  location = var.region
  template {
    template {
      service_account = google_service_account.runtime.email
      timeout         = "14400s"
      max_retries     = 0
      containers {
        image   = var.image
        command = ["python"]
        args    = ["-m", "bgb", "run-due"]
        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
        env {
          name  = "BGB_USE_GCP"
          value = "1"
        }
        env {
          name  = "BGB_INDEX"
          value = "firestore"
        }
        env {
          name  = "BGB_VOLUMES"
          value = "gcs"
        }
        env {
          name  = "BGB_GCS_BUCKET"
          value = google_storage_bucket.backups.name
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
      }
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_job_iam_member" "runtime_invokes" {
  name     = google_cloud_run_v2_job.backup.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invokes" {
  name     = google_cloud_run_v2_job.backup.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "run_due" {
  name      = "bgb-run-due"
  region    = var.region
  schedule  = "*/15 * * * *"
  time_zone = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${local.backup_job_name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  depends_on = [google_project_service.required, google_cloud_run_v2_job_iam_member.scheduler_invokes]
}
