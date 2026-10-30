#!/usr/bin/env bash
# Build the Cloud Run image and apply terraform/.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
: "${PROJECT:?set PROJECT}"
: "${BUCKET:?set BUCKET to a globally unique Cloud Storage name}"
REGION="${REGION:-us-central1}"
TAG="${TAG:-latest}"
IMAGE="${IMAGE:-${REGION}-docker.pkg.dev/${PROJECT}/bgb/bgb:${TAG}}"

gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  --project "$PROJECT"

if ! gcloud artifacts repositories describe bgb --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create bgb \
    --repository-format=docker \
    --location "$REGION" \
    --project "$PROJECT"
fi

gcloud builds submit "$root" --tag "$IMAGE" --project "$PROJECT"

if ! command -v terraform >/dev/null 2>&1; then
  echo "Image pushed to ${IMAGE}."
  echo "Install Terraform, then run: terraform -chdir=terraform init && terraform -chdir=terraform apply -var project_id=${PROJECT} -var region=${REGION} -var bucket_name=${BUCKET} -var image=${IMAGE}"
  exit 0
fi

terraform -chdir="$root/terraform" init
terraform -chdir="$root/terraform" apply \
  -var "project_id=${PROJECT}" \
  -var "region=${REGION}" \
  -var "bucket_name=${BUCKET}" \
  -var "image=${IMAGE}"
