"""Checks on CI-CD-SETUP.md and the README Deploy section. Text based, like test_cloudbuild.py."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "CI-CD-SETUP.md").read_text()
README = (ROOT / "README.md").read_text()

ROLLBACK = "gcloud deploy targets rollback prod --delivery-pipeline=bgb --region=REGION --project=PROJECT"

REQUIRED_HEADINGS = [
    "Architecture",
    "Triggers",
    "Service accounts and roles",
    "GitHub connection and setup",
    "Running a trigger by hand",
    "Finding the live release",
    "Rollback",
    "Redeploying a known-good build",
    "Troubleshooting the first build",
    "Adding an environment",
    "Cutover checklist",
]


def _headings() -> set[str]:
    return {
        m.group(1).strip() for m in re.finditer(r"^#{1,4} (.+)$", GUIDE, re.MULTILINE)
    }


def _section(title: str) -> str:
    start = GUIDE.index(f"\n## {title}\n")
    nxt = GUIDE.find("\n## ", start + 1)
    return GUIDE[start : nxt if nxt != -1 else len(GUIDE)]


def test_required_headings_exist():
    missing = [h for h in REQUIRED_HEADINGS if h not in _headings()]
    assert not missing


def test_architecture_names_the_pipeline_parts():
    arch = _section("Architecture")
    for part in [
        "bgb-pr",
        "bgb-main",
        "Artifact Registry",
        "Cloud Deploy",
        "prod",
        "bgb-backup",
    ]:
        assert part in arch


def test_trigger_by_hand_and_live_release_commands():
    assert "gcloud builds triggers run bgb-main --branch=main --region=REGION" in GUIDE
    live = _section("Finding the live release")
    assert "gcloud deploy targets describe prod" in live
    assert "gcloud deploy releases list" in live
    assert "gcloud run services describe" in live


def test_rollback_command_and_untested_status():
    rollback = _section("Rollback")
    assert ROLLBACK in rollback
    assert "not yet tested" in rollback
    assert "Test steps" in rollback


def test_no_workstation_deploy_path():
    # epics.md D12: releases only come from Cloud Build and Cloud Deploy.
    assert "## Manual fallback deploy" not in GUIDE
    redeploy = _section("Redeploying a known-good build")
    assert "bgb-main" in redeploy
    assert "gcloud deploy releases create" not in redeploy


def test_cutover_outcomes_not_recorded():
    cutover = _section("Cutover checklist")
    assert "not yet recorded" in cutover
    assert "done" not in cutover.lower().replace("do not mark an item done", "")


def test_existing_facts_kept():
    for fact in [
        "bgb-cloudbuild",
        "bgb-deployer",
        "roles/cloudquotas.viewer",
        "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY",
        "enforce_admins",
        "gcr.io/cloud-builders/docker:24.0.9",
        "Decision DEP-D1",
    ]:
        assert fact in GUIDE


def test_no_cors_origins_or_api_token_example():
    assert "BGB_CORS_ORIGINS=" not in GUIDE
    assert "BGB_API_TOKEN" not in GUIDE


def test_readme_deploy_section():
    deploy = README[README.index("\n## Deploy\n") :]
    assert "CI-CD-SETUP.md" in deploy
    assert "bootstrap" in deploy
    assert "Terraform owns infrastructure" in deploy
    assert "Cloud Build and Cloud Deploy own the image" in deploy
    assert ":latest" not in README
