# Admin console access: external HTTPS load balancer with IAP in front of the Cloud Run service.
# Aviato org policy run.allowedIngress allows only internal-and-cloud-load-balancing, so this is
# the only way in (epics.md D7, Story 5.2). IAP uses the Google-managed OAuth client.

data "google_project" "this" {
  project_id = var.project_id
}

# Google creates the IAP service agent on first use; create it explicitly so the invoker
# binding below has an account to bind.
resource "google_project_service_identity" "iap" {
  provider   = google-beta
  project    = var.project_id
  service    = "iap.googleapis.com"
  depends_on = [google_project_service.required]
}

locals {
  iap_service_agent = google_project_service_identity.iap.email
  # The audience in IAP's signed header for a global backend service (Story 5.1 verifies it).
  iap_audience = "/projects/${data.google_project.this.number}/global/backendServices/${google_compute_backend_service.console.generated_id}"
}

resource "google_compute_global_address" "console" {
  name       = "bgb-console"
  depends_on = [google_project_service.required]
}

resource "google_compute_region_network_endpoint_group" "console" {
  name                  = "bgb-console"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.ui.name
  }
}

resource "google_compute_backend_service" "console" {
  name                  = "bgb-console"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.console.id
  }

  iap {
    enabled = true
  }

  log_config {
    enable = true
  }
}

resource "google_compute_url_map" "console" {
  name            = "bgb-console"
  default_service = google_compute_backend_service.console.id
}

resource "google_compute_managed_ssl_certificate" "console" {
  name = "bgb-console"
  managed {
    domains = [var.console_hostname]
  }
  depends_on = [google_project_service.required]
}

resource "google_compute_target_https_proxy" "console" {
  name             = "bgb-console"
  url_map          = google_compute_url_map.console.id
  ssl_certificates = [google_compute_managed_ssl_certificate.console.id]
}

resource "google_compute_global_forwarding_rule" "console_https" {
  name                  = "bgb-console-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.console.id
  port_range            = "443"
  target                = google_compute_target_https_proxy.console.id
}

# Plain HTTP only redirects to HTTPS.
resource "google_compute_url_map" "console_redirect" {
  name = "bgb-console-redirect"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "console_redirect" {
  name    = "bgb-console-redirect"
  url_map = google_compute_url_map.console_redirect.id
}

resource "google_compute_global_forwarding_rule" "console_http" {
  name                  = "bgb-console-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.console.id
  port_range            = "80"
  target                = google_compute_target_http_proxy.console_redirect.id
}

# Who may pass IAP.
resource "google_iap_web_backend_service_iam_member" "console_access" {
  project             = var.project_id
  web_backend_service = google_compute_backend_service.console.name
  role                = "roles/iap.httpsResourceAccessor"
  member              = "group:${var.console_access_group}"
}

# IAP calls Cloud Run as its service agent, so the agent needs invoker on the service.
resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  name       = google_cloud_run_v2_service.ui.name
  location   = var.region
  role       = "roles/run.invoker"
  member     = "serviceAccount:${local.iap_service_agent}"
  depends_on = [google_compute_backend_service.console]
}
