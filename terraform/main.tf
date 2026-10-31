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
  backup_project  = var.backup_project_id != "" ? var.backup_project_id : var.project_id
  separate_backup = local.backup_project != var.project_id
  # Static keys so for_each works before the accounts exist.
  app_accounts = {
    run = google_service_account.runtime.email
    ui  = google_service_account.ui.email
  }
  services = concat([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "clouddeploy.googleapis.com",
    "iamcredentials.googleapis.com",
    "containerscanning.googleapis.com",
    "cloudquotas.googleapis.com",
  ], var.kms_key_name == "" ? [] : ["cloudkms.googleapis.com"])
}

resource "google_project_service" "required" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service" "backup_storage" {
  count              = local.separate_backup ? 1 : 0
  project            = local.backup_project
  service            = "storage.googleapis.com"
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
  project    = local.backup_project
  depends_on = [google_project_service.required, google_project_service.backup_storage]
}

resource "google_kms_crypto_key_iam_member" "gcs_agent" {
  count         = local.use_cmek ? 1 : 0
  crypto_key_id = var.kms_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs[0].email_address}"
}

resource "google_kms_crypto_key_iam_member" "runtime" {
  for_each      = local.use_cmek ? local.app_accounts : {}
  crypto_key_id = var.kms_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${each.value}"
}

resource "google_storage_bucket" "backups" {
  name                        = var.bucket_name
  project                     = local.backup_project
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  # Deleted objects stay restorable for this long. Only bucket admins can shorten it,
  # and no bgb account is a bucket admin.
  soft_delete_policy {
    retention_duration_seconds = var.soft_delete_days * 86400
  }

  # No object can be deleted or replaced until it is this old, by any account.
  # Locking makes the period permanent: it can then be raised but never lowered or removed.
  dynamic "retention_policy" {
    for_each = var.object_retention_days > 0 ? [var.object_retention_days] : []
    content {
      retention_period = retention_policy.value * 86400
      is_locked        = var.lock_retention
    }
  }

  dynamic "encryption" {
    for_each = local.use_cmek ? [var.kms_key_name] : []
    content {
      default_kms_key_name = encryption.value
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_service.backup_storage,
    google_kms_crypto_key_iam_member.gcs_agent,
    google_kms_crypto_key_iam_member.runtime,
  ]
}

# Three identities, so the internet-facing UI cannot delete backups:
#   bgb-run       the backup job. Writes and deletes stored objects.
#   bgb-ui        the UI service. Reads stored objects; starts the job for anything destructive.
#   bgb-delegate  the Workspace domain-wide delegation account. No Google Cloud roles at all.
resource "google_service_account" "runtime" {
  account_id   = "bgb-run"
  display_name = "bgb backup job"
}

resource "google_service_account" "ui" {
  account_id   = "bgb-ui"
  display_name = "bgb UI service"
}

resource "google_service_account" "delegate" {
  account_id   = "bgb-delegate"
  display_name = "bgb Workspace delegation"
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

resource "google_storage_bucket_iam_member" "ui_objects" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ui.email}"
}

resource "google_project_iam_member" "firestore" {
  for_each = local.app_accounts
  project  = var.project_id
  role     = "roles/datastore.user"
  member   = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "secrets" {
  for_each = local.app_accounts
  project  = var.project_id
  role     = "roles/secretmanager.secretAccessor"
  member   = "serviceAccount:${each.value}"
}

# Lets the job and the UI sign Workspace delegation JWTs as bgb-delegate without a JSON key.
# bgb-delegate holds no Google Cloud roles, so signing as it reaches Workspace only.
resource "google_service_account_iam_member" "delegate_signers" {
  for_each           = local.app_accounts
  service_account_id = google_service_account.delegate.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret" "workspace_sa" {
  secret_id = "bgb-workspace-sa"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "workspace_sa" {
  for_each  = local.app_accounts
  secret_id = google_secret_manager_secret.workspace_sa.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value}"
}

resource "google_cloud_run_v2_service" "ui" {
  name     = "bgb"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.ui.email
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
  # DEP-D1: Cloud Deploy owns the running image and Cloud Run runtime config. Terraform creates
  # this resource once with the bootstrap image, then ignores the template so a later apply
  # does not revert what a release deployed.
  lifecycle {
    ignore_changes = [template, client, client_version]
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
      # Runs checkpoint their progress, so a timeout or retry resumes rather than restarts.
      timeout     = "${var.job_timeout_hours * 3600}s"
      max_retries = var.job_max_retries
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
        env {
          name  = "BGB_OBJECT_RETENTION_DAYS"
          value = tostring(var.object_retention_days)
        }
      }
    }
  }
  # DEP-D1: see the lifecycle comment on google_cloud_run_v2_service.ui.
  lifecycle {
    ignore_changes = [template, client, client_version]
  }

  depends_on = [google_project_service.required]
}

# The UI starts the job with argument overrides ("Run now", rebuild, prune, delete).
resource "google_cloud_run_v2_job_iam_member" "ui_runs_job" {
  name     = google_cloud_run_v2_job.backup.name
  location = var.region
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${google_service_account.ui.email}"
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

# Deployment pipeline (Epic 8). Roles and reasons are documented in CI-CD-SETUP.md.
resource "google_artifact_registry_repository" "bgb" {
  repository_id = "bgb"
  location      = var.region
  format        = "DOCKER"
  description   = "bgb container images"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-recent-tagged"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }

  # KEEP wins over DELETE, so the newest 20 versions survive. Older tagged versions go after
  # 30 days, which leaves recent rollback targets in place.
  cleanup_policies {
    id     = "delete-old-tagged"
    action = "DELETE"
    condition {
      tag_state  = "TAGGED"
      older_than = "2592000s"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "cloudbuild" {
  account_id   = "bgb-cloudbuild"
  display_name = "bgb Cloud Build"
}

resource "google_service_account" "deployer" {
  account_id   = "bgb-deployer"
  display_name = "bgb Cloud Deploy execution"
}

# bgb-cloudbuild: runs builds, pushes images and creates releases.
resource "google_project_iam_member" "cloudbuild_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_project_iam_member" "cloudbuild_releaser" {
  project = var.project_id
  role    = "roles/clouddeploy.releaser"
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.bgb.location
  repository = google_artifact_registry_repository.bgb.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Creating a release makes Cloud Deploy run as bgb-deployer.
resource "google_service_account_iam_member" "cloudbuild_acts_as_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# bgb-deployer: executes Cloud Deploy rollouts onto Cloud Run.
resource "google_project_iam_member" "deployer_job_runner" {
  project = var.project_id
  role    = "roles/clouddeploy.jobRunner"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_service" {
  name     = google_cloud_run_v2_service.ui.name
  location = var.region
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_job_iam_member" "deployer_job" {
  name     = google_cloud_run_v2_job.backup.name
  location = var.region
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.bgb.location
  repository = google_artifact_registry_repository.bgb.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision that runs as an app account needs actAs on that account, and on no other.
resource "google_service_account_iam_member" "deployer_acts_as_app" {
  for_each           = { run = google_service_account.runtime.name, ui = google_service_account.ui.name }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# Lets the job read its own quota usage (Story 10.2 pacing).
resource "google_project_iam_member" "runtime_quota_viewer" {
  project = var.project_id
  role    = "roles/cloudquotas.viewer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# GitHub connection and triggers (Story 8.2). The OAuth handshake is manual: create the connection
# in the console, then import it. github_config is ignored so the OAuth credentials never show as
# a diff. See CI-CD-SETUP.md.
resource "google_cloudbuildv2_connection" "github" {
  project  = var.project_id
  location = var.region
  name     = var.github_connection_name

  github_config {}

  lifecycle {
    ignore_changes = [github_config]
  }

  depends_on = [google_project_service.required]
}

resource "google_cloudbuildv2_repository" "bgb" {
  project           = var.project_id
  location          = var.region
  name              = "bgb"
  parent_connection = google_cloudbuildv2_connection.github.name
  remote_uri        = var.github_repository_uri
}

# Pull requests to main. Owners and collaborators run unprompted. Anyone else waits for a
# maintainer to comment /gcbrun, so outside code never runs with project credentials unreviewed.
resource "google_cloudbuild_trigger" "pr" {
  project         = var.project_id
  location        = var.region
  name            = "bgb-pr"
  description     = "Tests and checks for pull requests to main"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.cloudbuild.id

  repository_event_config {
    repository = google_cloudbuildv2_repository.bgb.id
    pull_request {
      branch          = "^main$"
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }

  substitutions = {
    _MODE = "pr"
  }
}

# Pushes to main: build, push and release. Tests are not rerun, so branch protection must
# require the bgb-pr check (CI-CD-SETUP.md).
resource "google_cloudbuild_trigger" "main" {
  project         = var.project_id
  location        = var.region
  name            = "bgb-main"
  description     = "Build, push and release on merge to main"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.cloudbuild.id

  repository_event_config {
    repository = google_cloudbuildv2_repository.bgb.id
    push {
      branch = "^main$"
    }
  }

  substitutions = {
    _MODE = "main"
  }
}
