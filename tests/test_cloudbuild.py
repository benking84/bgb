"""Checks on cloudbuild.yaml. Text based, so no YAML dependency."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = (ROOT / "cloudbuild.yaml").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()

IMAGE = "${_REGION}-docker.pkg.dev/${PROJECT_ID}/bgb/bgb"


def _steps() -> dict[str, str]:
    body = BUILD[BUILD.index("\nsteps:") :]
    chunks = re.split(r"\n  - id: ", body)[1:]
    return {c.split("\n", 1)[0].strip(): c for c in chunks}


STEPS = _steps()


def test_expected_steps_in_order():
    ids = list(STEPS)
    assert ids.index("validate-mode") < ids.index("guard-release") < ids.index("install-deps-python")
    assert ids.index("guard-release") < ids.index("build-image")
    assert ids.index("build-image") < ids.index("read-digest") < ids.index("create-release")


def test_no_latest_tag():
    assert ":latest" not in BUILD
    assert "latest" not in re.sub(r"#.*", "", BUILD)
    assert "latest" not in DOCKERFILE


def test_image_path_and_push():
    assert "_REGION: us-central1" in BUILD
    build = STEPS["build-image"]
    assert f"{IMAGE}:${{COMMIT_SHA}}" in build
    assert "docker push" in build
    assert "docker push" not in "".join(v for k, v in STEPS.items() if k != "build-image")
    # PR build never pushes: the push is after the PR branch exits.
    assert build.index("exit 0") < build.index("docker push")
    assert "bgb:pr-check" in build


def test_guard_requires_main_mode_and_branch():
    guard = STEPS["guard-release"]
    assert '"${_MODE}" != "main"' in guard
    assert '"$BRANCH_NAME" != "main"' in guard
    assert "exit 1" in guard


def test_release_by_digest_with_annotations():
    assert "sha256:" in STEPS["read-digest"]
    assert "/workspace/image-digest" in STEPS["read-digest"]
    release = STEPS["create-release"]
    assert '"sha-${SHORT_SHA}"' in release
    assert "--delivery-pipeline=bgb" in release
    assert "--source=deploy" in release
    assert f"bgb={IMAGE}@$$DIGEST" in release
    assert "/workspace/image-digest" in release
    assert "${COMMIT_SHA}" in release and "${BUILD_ID}" in release
    assert "--annotations=" in release


def test_main_path_runs_no_tests():
    test_cmds = ("pytest", "ruff ", "npm run lint", "npm run build", "terraform ")
    for name, step in STEPS.items():
        if not any(c in step for c in test_cmds):
            continue
        assert name.startswith(("test-pr-only", "install-deps")), name
        assert f'if [ "${{_MODE}}" != "pr" ]; then echo "Skipping {name}' in step, name
    for name in ("read-digest", "create-release"):
        assert f'if [ "${{_MODE}}" != "main" ]; then echo "Skipping {name}' in STEPS[name]


def test_builder_images_pinned_and_options_kept():
    for image in re.findall(r"^    name: (\S+)", BUILD, re.M):
        assert re.search(r":\d[\w.\-]*$", image), image
    assert "logging: CLOUD_LOGGING_ONLY" in BUILD
    assert re.search(r"^timeout: \d+s", BUILD, re.M)


def test_dockerfile_installs_from_lock():
    assert "uv sync --locked --no-dev --no-editable" in DOCKERFILE
    assert "uv.lock" in DOCKERFILE
    assert "pip install" not in DOCKERFILE
    assert "/app/.venv/bin" in DOCKERFILE
