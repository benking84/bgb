### DW-1: The Cloud Deploy service agent may need roles/iam.serviceAccountUser on bgb-deployer.
origin: spec-deferred db53eaf37a56
location: terraform/main.tf, bgb-deployer bindings
source_spec: `spec-8-1-terraform-foundations-for-the-pipeline.md`
severity: medium
reason: Edge-case reviewer raised it from Cloud Deploy documentation recall; nothing in the repo settles it. The first rollout in Story 8.4 shows whether it is needed. Recorded in CI-CD-SETUP.md. (declared severity: medium (unverified))
status: open

### DW-2: Cloud Deploy may write labels, annotations or traffic settings that Terraform then reports as drift on the service and job.
origin: spec-deferred cae4cff20b38
location: terraform/main.tf, lifecycle blocks
source_spec: `spec-8-1-terraform-foundations-for-the-pipeline.md`
severity: medium
reason: ignore_changes covers template, client and client_version only. A terraform plan after the first rollout (Story 8.4) shows whether more fields are needed. Recorded in CI-CD-SETUP.md. (declared severity: medium (unverified))
status: open

### DW-3: bgb-cloudbuild may need storage access for the Cloud Deploy artifacts bucket when it creates a release.
origin: spec-deferred fd8851bad5d3
location: terraform/main.tf, bgb-cloudbuild bindings
source_spec: `spec-8-1-terraform-foundations-for-the-pipeline.md`
severity: medium
reason: Already listed as an assumption in CI-CD-SETUP.md. The first main build in Story 8.5 shows whether releases fail with a storage 403. (declared severity: medium (unverified))
status: open
