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

### DW-4: Any repository collaborator can change cloudbuild.yaml in a PR and run it as bgb-cloudbuild, which holds release and image push rights.
origin: spec-deferred 81bcf3ce86c6
location: terraform/main.tf, google_cloudbuild_trigger.pr service_account
source_spec: `spec-8-2-github-connection-triggers-and-branch-protection.md`
severity: medium
reason: Both triggers run as bgb-cloudbuild by the story's own acceptance criteria, and guard-release in Story 8.5 keys on BRANCH_NAME, which for PR triggers is likely the base branch. Whether a separate low-privilege PR account is needed is a design decision for Stories 8.3 and 8.5. Recorded in CI-CD-SETUP.md. (declared severity: medium (unverified))
status: open

### DW-5: terraform init resolves provider versions fresh on every PR build because no .terraform.lock.hcl is committed.
origin: spec-deferred 5f1550d00d82
location: terraform/, cloudbuild.yaml test-pr-only-terraform
source_spec: `spec-8-3-pull-request-path-tests-and-checks-run-once.md`
severity: low
reason: terraform/ holds no lock file and .gitignore excludes only .terraform/. A new provider release could change validate results with no repo change. Pre-existing from Story 8.1; fix is to commit the lock file after an init with provider access.
status: open

### DW-6: The four builder image tags were not pulled, so one may not exist.
origin: spec-deferred a322fe8acd1a
location: cloudbuild.yaml
source_spec: `spec-8-3-pull-request-path-tests-and-checks-run-once.md`
severity: medium
reason: Versions were taken from local tool versions and known release lines. A missing tag fails every PR build at the first pull. Settled by pulling or running the first real build. (declared severity: medium (unverified))
status: open

### DW-7: The Story 8.4 acceptance criterion that cloudbuild.yaml passes the Skaffold config when it creates the release is not met here.
origin: spec-deferred 4fb1c086df89
location: cloudbuild.yaml
source_spec: `spec-8-4-cloud-deploy-pipeline-and-cloud-run-manifests-prod-only.md`
severity: medium
reason: The create-release step belongs to Story 8.5 and 8.3 forbade it. CI-CD-SETUP.md records the exact release command for 8.5 (--source=deploy).
status: open

### DW-8: The manifest test compares env var names, not values, and depends on terraform fmt spacing in main.tf.
origin: spec-deferred 22fd4b5b6bd0
location: tests/test_deploy_manifests.py
source_spec: `spec-8-4-cloud-deploy-pipeline-and-cloud-run-manifests-prod-only.md`
severity: low
reason: tests/test_deploy_manifests.py checks name sets and exact aligned text such as the 3600s timeout line, so a wrong value passes and a reformat fails.
status: open

### DW-9: deploy_stage_order has no validation for empty or duplicate entries, and the missing-target check is a lifecycle precondition.
origin: spec-deferred 67fed56fa0d0
location: terraform/main.tf, terraform/variables.tf
source_spec: `spec-8-4-cloud-deploy-pipeline-and-cloud-run-manifests-prod-only.md`
severity: low
reason: An empty list gives a pipeline with no stages. Whether the precondition fires before an invalid index error is unconfirmed until terraform validate runs. (declared severity: low (unverified))
status: open
