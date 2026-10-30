from fastapi.testclient import TestClient

from bgb.api.app import create_app
from bgb.sources.demo import HANDBOOK
from tests.helpers import make_engine


def test_demo_backup_restore_and_second_run(tmp_path):
    runtime, _holder = make_engine(tmp_path)
    client = TestClient(create_app(runtime))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    seeded = client.post("/api/demo/seed")
    assert seeded.status_code == 200
    job_id = seeded.json()["id"]
    assert seeded.json()["demo"] is True

    rejected = client.post(
        "/api/jobs",
        json={"name": "Nope", "users": ["ada@example.com"], "sources": ["keep"]},
    )
    assert rejected.status_code == 400

    first = client.post(f"/api/jobs/{job_id}/run?wait=true")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "completed"
    assert body["stats"]["blocks_new"] > 0
    assert body["stats"]["blocks_reused"] > 0
    assert body["stats"]["verify"]["ok"] is True

    filesets = client.get(f"/api/jobs/{job_id}/filesets").json()
    fileset_id = filesets[0]["id"]
    listing = client.get(f"/api/jobs/{job_id}/filesets/{fileset_id}/files").json()
    paths = [row["path"] for row in listing["files"]]
    handbook = "drive/users/ada@northwind.example/Policies/handbook.pdf"
    shared = "drive/shared/drive-commons/Published/handbook.pdf"
    assert handbook in paths
    assert shared in paths
    assert any(path.startswith("gmail/") and path.endswith(".eml") for path in paths)
    assert any(path.startswith("contacts/") for path in paths)

    downloaded = client.get(
        f"/api/jobs/{job_id}/filesets/{fileset_id}/content",
        params={"path": handbook},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == HANDBOOK
    shared_bytes = client.get(
        f"/api/jobs/{job_id}/filesets/{fileset_id}/content",
        params={"path": shared},
    )
    assert shared_bytes.content == HANDBOOK

    second = client.post(f"/api/jobs/{job_id}/run?wait=true")
    assert second.status_code == 200, second.text
    assert second.json()["stats"]["blocks_new"] == 0
    assert second.json()["stats"]["files_unchanged"] == second.json()["stats"]["files"]

    verify = client.post(f"/api/jobs/{job_id}/verify?full=true")
    assert verify.json()["ok"] is True

    settings = client.get("/api/settings").json()
    settings["workspace_domain"] = "northwind.example"
    settings["admin_email"] = "admin@northwind.example"
    saved = client.put("/api/settings", json=settings)
    assert saved.status_code == 200
    assert client.get("/api/settings").json()["workspace_domain"] == "northwind.example"
    probe = client.post("/api/connection-test")
    assert probe.json()["mode"] == "local"

    missing = client.get(
        f"/api/jobs/{job_id}/filesets/{fileset_id}/content",
        params={"path": "drive/users/ada@northwind.example/missing.bin"},
    )
    assert missing.status_code == 404
