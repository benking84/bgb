"""Checks that deploy/*.yaml agree with terraform/main.tf. Text based, so no YAML dependency."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE = (ROOT / "deploy" / "service.yaml").read_text()
JOB = (ROOT / "deploy" / "job.yaml").read_text()
SKAFFOLD = (ROOT / "deploy" / "skaffold.yaml").read_text()
MAIN_TF = (ROOT / "terraform" / "main.tf").read_text()


def _block(text: str, start: str) -> str:
    """Terraform text from the line containing `start` to the next top level closing brace."""
    i = text.index(start)
    return text[i : text.index("\n}\n", i)]


SERVICE_TF = _block(MAIN_TF, 'resource "google_cloud_run_v2_service" "ui"')
JOB_TF = _block(MAIN_TF, 'resource "google_cloud_run_v2_job" "backup"')


def _env_names(text: str) -> list[str]:
    return re.findall(r"- name: (\w+)", text)


def _tf_env_names(text: str) -> list[str]:
    return re.findall(r'env \{\s*name\s*=\s*"(\w+)"', text)


def test_service_fixed_settings_match_terraform():
    assert "container_port = 8080" in SERVICE_TF
    assert "containerPort: 8080" in SERVICE
    assert 'timeout                          = "3600s"' in SERVICE_TF
    assert "timeoutSeconds: 3600" in SERVICE
    assert "max_instance_request_concurrency = 80" in SERVICE_TF
    assert "containerConcurrency: 80" in SERVICE
    assert 'cpu    = "1"' in SERVICE_TF and 'cpu: "1"' in SERVICE
    assert 'memory = "1Gi"' in SERVICE_TF and "memory: 1Gi" in SERVICE


def test_job_fixed_settings_match_terraform():
    assert 'cpu    = "2"' in JOB_TF and 'cpu: "2"' in JOB
    assert 'memory = "2Gi"' in JOB_TF and "memory: 2Gi" in JOB
    assert 'command = ["python"]' in JOB_TF
    assert 'args    = ["-m", "bgb", "run-due"]' in JOB_TF
    command = r"command:\s*- python\s*args:\s*- -m\s*- bgb\s*- run-due"
    assert re.search(command, JOB)
    assert "var.job_timeout_hours * 3600" in JOB_TF
    assert "{{.JOB_TIMEOUT_SECONDS}}" in JOB
    assert "var.job_max_retries" in JOB_TF
    assert "{{.JOB_MAX_RETRIES}}" in JOB


def test_env_vars_match_terraform_except_known_differences():
    # The service gains BGB_IAP_AUDIENCE (Design Notes). The job keeps its retention variable.
    assert set(_env_names(SERVICE)) == set(_tf_env_names(SERVICE_TF)) | {"BGB_IAP_AUDIENCE"}
    assert set(_env_names(JOB)) == set(_tf_env_names(JOB_TF))


def test_no_cors_env_and_iap_audience_is_a_parameter():
    for text in (SERVICE, JOB):
        assert "name: BGB_CORS_ORIGINS" not in text
    assert 'value: "{{.BGB_IAP_AUDIENCE}}"' in SERVICE
    assert 'value: "{{.BGB_OBJECT_RETENTION_DAYS}}"' in JOB


def test_image_is_the_placeholder():
    for text in (SERVICE, JOB):
        assert re.findall(r"image: (\S+)", text) == ["bgb"]


def test_skaffold_lists_both_manifests():
    assert "service.yaml" in SKAFFOLD and "job.yaml" in SKAFFOLD
    assert "cloudrun" in SKAFFOLD


def test_every_placeholder_has_a_terraform_parameter():
    locals_block = MAIN_TF[MAIN_TF.index("base_deploy_parameters = {") :]
    locals_block = locals_block[: locals_block.index("\n  }")]
    keys = set(re.findall(r"^\s+(\w+)\s+=", locals_block, re.M))
    keys.discard("base_deploy_parameters")
    used = set(re.findall(r"\{\{\.(\w+)\}\}", SERVICE + JOB))
    assert used, "no placeholders found"
    assert used <= keys, used - keys
    assert {"BGB_OBJECT_RETENTION_DAYS", "BGB_IAP_AUDIENCE"} <= keys


def test_no_hard_coded_environment_values():
    for text in (SERVICE, JOB, SKAFFOLD):
        assert "aviato" not in text
        assert not re.search(r"us-central1|@.*\.iam\.gserviceaccount\.com", text)
