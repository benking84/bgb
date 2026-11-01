from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import UTC, timedelta
from pathlib import Path

from bgb.engine import Engine
from bgb.errors import ConfigError, Conflict, Retained
from bgb.index.memory import FileIndex, MemoryIndex
from bgb.models import Job, Run
from bgb.schedule import is_due
from bgb.secretstore import FileSecrets, GcpSecrets, env_flag
from bgb.sources.factory import build_sources
from bgb.storage import GCSVolumeStore, LocalVolumeStore
from bgb.util import now_iso

log = logging.getLogger("bgb.runtime")


class Runtime:
    def __init__(self, index, volumes, secrets, data_dir: Path):
        self.index = index
        self.volumes = volumes
        self.secrets = secrets
        self.data_dir = data_dir
        self.engine = Engine(
            index,
            volumes,
            sources_for=lambda job, settings: build_sources(job, settings, secrets),
            min_object_age=timedelta(
                days=int(os.environ.get("BGB_OBJECT_RETENTION_DAYS") or 0)
            ),
        )

    def flush(self) -> None:
        self.index.flush()

    def start_backup(self, job_id: str, *, wait: bool = False) -> Run:
        self.index.get_job(job_id)
        if self.index.lease_holder(job_id):
            raise Conflict(
                "a backup or maintenance task for this job is already running"
            )
        run = Run(
            id=uuid.uuid4().hex,
            job_id=job_id,
            status="queued",
            phase="queued",
            started_at=now_iso(),
        )
        self.index.add_run(run)
        self.flush()
        cloud_job = os.environ.get("BGB_CLOUD_RUN_JOB", "").strip()
        if cloud_job and not wait:
            try:
                _trigger_cloud_run_job(
                    cloud_job, ["run", "--job-id", job_id, "--run-id", run.id]
                )
            except Exception as exc:
                run.status = "failed"
                run.phase = "failed"
                run.error = str(exc)
                run.finished_at = now_iso()
                self.index.update_run(run)
                self.flush()
                raise ConfigError(f"could not start Cloud Run job: {exc}") from exc
            return run
        if wait:
            return self.engine.run_backup(job_id, run.id)

        def target() -> None:
            try:
                self.engine.run_backup(job_id, run.id)
            except Exception:
                log.exception("background backup failed for %s", job_id)

        threading.Thread(target=target, name=f"bgb-{job_id[:8]}", daemon=True).start()
        return run

    def run_due(self) -> list[Run]:
        from datetime import datetime

        now = datetime.now(UTC)
        started: list[Run] = []
        for job in self.index.list_jobs():
            if not job.enabled or not job.schedule:
                continue
            if self.index.lease_holder(job.id):
                continue
            runs = self.index.list_runs(job.id)
            last = runs[0].started_at if runs else None
            if is_due(job.schedule, job.created_at or now_iso(), last, now):
                try:
                    started.append(self.engine.run_backup(job.id))
                except Conflict as exc:
                    log.info("skipped job=%s: %s", job.id, exc)
        return started

    def in_backup_job(self, args: list[str]) -> bool:
        """On Cloud Run, start the backup job with these CLI args and return True.

        Deleting and rebuilding run there because only the job's account may
        delete stored objects; the UI service's account can read them only.
        """
        cloud_job = os.environ.get("BGB_CLOUD_RUN_JOB", "").strip()
        if not cloud_job:
            return False
        _trigger_cloud_run_job(cloud_job, args)
        return True

    def delete_job(self, job_id: str) -> dict:
        """Delete the job and its stored objects. Objects still under bucket retention stay until it ends."""
        self.index.get_job(job_id)
        retained = 0
        with self.engine.leased(job_id):
            for volume in self.index.list_volumes(job_id):
                try:
                    self.volumes.delete(volume.name)
                except Retained:
                    retained += 1
            self.index.delete_job(job_id)
        self.flush()
        return {"deleted": job_id, "objects_retained": retained}


def build_runtime() -> Runtime:
    data = Path(os.environ.get("BGB_DATA_DIR", "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    use_gcp = env_flag("BGB_USE_GCP")
    index_kind = os.environ.get("BGB_INDEX", "firestore" if use_gcp else "file")
    volume_kind = os.environ.get("BGB_VOLUMES", "gcs" if use_gcp else "file")
    if index_kind == "firestore":
        from google.cloud import firestore

        from bgb.index.firestore import FirestoreIndex

        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
        index = FirestoreIndex(firestore.Client(project=project))
    elif index_kind == "memory":
        index = MemoryIndex()
    else:
        index = FileIndex(data / "index.json")
    settings = index.get_settings()
    if os.environ.get("BGB_GCS_BUCKET"):
        settings.gcs_bucket = os.environ["BGB_GCS_BUCKET"]
    if os.environ.get("BGB_GCS_PREFIX"):
        settings.gcs_prefix = os.environ["BGB_GCS_PREFIX"]
    index.save_settings(settings)
    if volume_kind == "gcs":
        if not settings.gcs_bucket:
            raise ConfigError(
                "Set BGB_GCS_BUCKET or the bucket in settings before using Cloud Storage"
            )
        volumes = GCSVolumeStore(settings.gcs_bucket)
    else:
        volumes = LocalVolumeStore(data / "volumes")
    if use_gcp and os.environ.get("BGB_SECRETS", "gcp") != "file":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            raise ConfigError("GOOGLE_CLOUD_PROJECT is required when BGB_USE_GCP=1")
        secrets = GcpSecrets(project)
    else:
        secrets = FileSecrets(data / "secrets")
    index.flush()
    return Runtime(index, volumes, secrets, data)


def _trigger_cloud_run_job(name: str, args: list[str]) -> None:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    response = session.post(
        f"https://run.googleapis.com/v2/{name}:run",
        json={"overrides": {"containerOverrides": [{"args": ["-m", "bgb", *args]}]}},
        timeout=60,
    )
    if response.status_code >= 300:
        raise ConfigError(response.text[:500])


def seed_demo(runtime: Runtime) -> Job:
    from bgb.errors import NotFound

    try:
        job = runtime.index.get_job("northwind")
    except NotFound:
        job = Job(
            id="northwind",
            name="Northwind campus",
            created_at=now_iso(),
        )
    job.name = "Northwind campus"
    job.description = (
        "Sample Workspace with two people, mail, My Drive, a shared drive, and contacts. "
        "The faculty handbook is in two drives; identical blocks are stored once."
    )
    job.users = ["ada@northwind.example", "grace@northwind.example"]
    job.all_users = False
    job.sources = ["gmail", "drive", "contacts"]
    job.include_shared_drives = True
    job.retention = "policy:1W:1D,4W:1W,12M:1M"
    job.schedule = ""
    job.enabled = True
    job.demo = True
    job.block_size = 64
    job.volume_size = 8192
    job.updated_at = now_iso()
    job.created_at = job.created_at or now_iso()
    runtime.index.upsert_job(job)
    runtime.flush()
    return job
