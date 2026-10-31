from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bgb import __version__
from bgb.errors import BgbError, ConfigError
from bgb.models import Job, Settings
from bgb.retention import describe_retention, parse_retention
from bgb.runtime import Runtime, build_runtime, seed_demo
from bgb.schedule import validate_schedule
from bgb.sources.catalog import DIRECTORY_SCOPE, SOURCE_CATALOG
from bgb.sources.factory import probe_connection
from bgb.util import from_dict, now_iso


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    users: list[str] = Field(default_factory=list)
    all_users: bool = False
    sources: list[str] = Field(default_factory=lambda: ["gmail", "drive"])
    include_shared_drives: bool = True
    retention: str = "policy:1W:1D,4W:1W,12M:1M"
    schedule: str = ""
    enabled: bool = True
    demo: bool = False
    block_size: int | None = None
    volume_size: int | None = None


class SettingsIn(BaseModel):
    workspace_domain: str = ""
    admin_email: str = ""
    auth_mode: str = "service_account"
    service_account_secret: str = "bgb-workspace-sa"
    service_account_email: str = ""
    oauth_secret: str = "bgb-oauth-client"
    gcs_bucket: str = ""
    gcs_prefix: str = "bgb"
    block_size: int = 102400
    volume_size: int = 50 * 1024 * 1024
    verify_samples: int = 1
    compact_waste_threshold: float = 0.25


def create_app(runtime: Runtime | None = None) -> FastAPI:
    app = FastAPI(title="bgb", version=__version__)
    app.state.runtime = runtime or build_runtime()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def token_gate(request: Request, call_next):
        expected = os.environ.get("BGB_API_TOKEN", "").strip()
        if (
            expected
            and request.url.path.startswith("/api")
            and request.url.path != "/api/health"
        ):
            header = request.headers.get("authorization", "")
            if header != f"Bearer {expected}":
                return JSONResponse(
                    {"error": "unauthorized", "code": "unauthorized"}, status_code=401
                )
        return await call_next(request)

    @app.exception_handler(BgbError)
    async def handle_bgb(_request: Request, exc: BgbError):
        return JSONResponse(
            {"error": str(exc), "code": exc.code}, status_code=exc.status
        )

    @app.get("/api/health")
    def health():
        rt = _rt(app)
        return {
            "ok": True,
            "version": __version__,
            "index": rt.index.__class__.__name__,
            "volumes": rt.volumes.__class__.__name__,
            "gcp": os.environ.get("BGB_USE_GCP", ""),
        }

    @app.get("/api/sources")
    def sources():
        return {"sources": SOURCE_CATALOG, "directory_scope": DIRECTORY_SCOPE}

    @app.get("/api/summary")
    def summary():
        rt = _rt(app)
        stored = 0
        volumes = 0
        blocks = 0
        last = None
        jobs = rt.index.list_jobs()
        for job in jobs:
            for volume in rt.index.list_volumes(job.id):
                if volume.kind == "dblock":
                    stored += volume.size
                    volumes += 1
            blocks += rt.index.count_blocks(job.id)
            for run in rt.index.list_runs(job.id):
                if run.status == "completed" and run.finished_at:
                    if last is None or run.finished_at > last:
                        last = run.finished_at
                    break
        return {
            "jobs": len(jobs),
            "stored_bytes": stored,
            "volumes": volumes,
            "blocks": blocks,
            "last_success": last,
        }

    @app.get("/api/settings")
    def get_settings():
        return _rt(app).index.get_settings().to_dict()

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        _validate_sizes(body.block_size, body.volume_size)
        if body.auth_mode not in {"service_account", "oauth"}:
            raise ConfigError("auth_mode must be service_account or oauth")
        if not 0 < body.compact_waste_threshold <= 1:
            raise ConfigError("compact threshold must be between 0 and 1")
        if body.verify_samples < 0:
            raise ConfigError("verify_samples cannot be negative")
        settings = from_dict(Settings, body.model_dump())
        rt = _rt(app)
        rt.index.save_settings(settings)
        rt.flush()
        return settings.to_dict()

    @app.post("/api/connection-test")
    def connection_test():
        rt = _rt(app)
        return probe_connection(rt.index.get_settings(), rt.secrets)

    @app.post("/api/demo/seed")
    def demo_seed():
        return _job_view(_rt(app), seed_demo(_rt(app)))

    @app.get("/api/jobs")
    def list_jobs():
        rt = _rt(app)
        return [_job_view(rt, job) for job in rt.index.list_jobs()]

    @app.post("/api/jobs")
    def create_job(body: JobIn):
        rt = _rt(app)
        _validate_job(body, rt.index.get_settings())
        job = Job(
            id=os.urandom(6).hex(),
            created_at=now_iso(),
            updated_at=now_iso(),
            **body.model_dump(),
        )
        rt.index.upsert_job(job)
        rt.flush()
        return _job_view(rt, job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        rt = _rt(app)
        return _job_view(rt, rt.index.get_job(job_id))

    @app.patch("/api/jobs/{job_id}")
    def patch_job(job_id: str, body: JobIn):
        rt = _rt(app)
        current = rt.index.get_job(job_id)
        _validate_job(body, rt.index.get_settings())
        if (
            body.block_size
            and body.block_size != current.block_size
            and rt.index.list_filesets(job_id)
        ):
            raise ConfigError("block size cannot change after the first backup")
        updated = Job(
            id=current.id,
            created_at=current.created_at,
            source_state=current.source_state,
            updated_at=now_iso(),
            **body.model_dump(),
        )
        rt.index.upsert_job(updated)
        rt.flush()
        return _job_view(rt, updated)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str):
        _rt(app).index.get_job(job_id)
        if _rt(app).in_backup_job(["delete-job", "--job-id", job_id]):
            return {"deleted": job_id, "queued": True}
        return _rt(app).delete_job(job_id)

    @app.post("/api/jobs/{job_id}/run")
    def run_job(job_id: str, wait: bool = False):
        run = _rt(app).start_backup(job_id, wait=wait)
        return run.to_dict()

    @app.get("/api/jobs/{job_id}/runs")
    def list_runs(job_id: str):
        rt = _rt(app)
        rt.index.get_job(job_id)
        return [run.to_dict() for run in rt.index.list_runs(job_id)]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return _rt(app).index.get_run(run_id).to_dict()

    @app.get("/api/jobs/{job_id}/filesets")
    def list_filesets(job_id: str):
        rt = _rt(app)
        rt.index.get_job(job_id)
        return [row.to_dict() for row in rt.index.list_filesets(job_id)]

    @app.get("/api/jobs/{job_id}/filesets/{fileset_id}/files")
    def list_files(
        job_id: str,
        fileset_id: str,
        prefix: str = "",
        cursor: str = "",
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        rt = _rt(app)
        rt.index.get_fileset(job_id, fileset_id)
        rows, next_cursor = rt.index.list_entries(
            job_id, fileset_id, prefix=prefix, cursor=cursor, limit=limit
        )
        return {"files": [row.to_dict() for row in rows], "next_cursor": next_cursor}

    @app.get("/api/jobs/{job_id}/filesets/{fileset_id}/content")
    def file_content(job_id: str, fileset_id: str, path: str):
        data, entry = _rt(app).engine.read_file(job_id, fileset_id, path)
        leaf = entry.path.rsplit("/", 1)[-1].replace('"', "")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{leaf}"'},
        )

    @app.post("/api/jobs/{job_id}/verify")
    def verify_job(job_id: str, full: bool = False):
        _rt(app).index.get_job(job_id)
        return _rt(app).engine.verify(job_id, full=full)

    @app.post("/api/jobs/{job_id}/prune")
    def prune_job(job_id: str):
        _rt(app).index.get_job(job_id)
        if _rt(app).in_backup_job(["prune", "--job-id", job_id]):
            return {"removed": [], "queued": True}
        removed = _rt(app).engine.prune_orphans(job_id)
        _rt(app).flush()
        return {"removed": removed}

    @app.post("/api/jobs/{job_id}/rebuild")
    def rebuild_job(job_id: str):
        _rt(app).index.get_job(job_id)
        if _rt(app).in_backup_job(["rebuild", "--job-id", job_id]):
            return {"queued": True}
        return _rt(app).engine.rebuild(job_id)

    web_root = os.environ.get("BGB_WEB_ROOT", "")
    if web_root and Path(web_root).is_dir():
        app.mount("/", StaticFiles(directory=web_root, html=True), name="ui")
    return app


def _rt(app: FastAPI) -> Runtime:
    return app.state.runtime


def _validate_sizes(block_size: int, volume_size: int) -> None:
    if block_size < 16 or block_size > 16 * 1024 * 1024:
        raise ConfigError("block size must be between 16 bytes and 16 MiB")
    if volume_size < block_size or volume_size > 128 * 1024 * 1024:
        raise ConfigError(
            "volume size must be at least the block size and at most 128 MiB"
        )


def _validate_job(body: JobIn, settings: Settings) -> None:
    from bgb.sources.catalog import SUPPORTED_SOURCES

    if not body.sources:
        raise ConfigError("pick at least one source")
    unknown = [name for name in body.sources if name not in SUPPORTED_SOURCES]
    if unknown:
        raise ConfigError(
            "unsupported sources: "
            + ", ".join(unknown)
            + ". Google Keep has no Workspace API."
        )
    if not body.users and not body.all_users and not body.demo:
        raise ConfigError("list at least one user, or choose every user in the domain")
    for user in body.users:
        if "@" not in user:
            raise ConfigError(f"{user!r} is not an email address")
    parse_retention(body.retention)
    validate_schedule(body.schedule)
    block = body.block_size or settings.block_size
    volume = body.volume_size or settings.volume_size
    _validate_sizes(block, volume)


def _job_view(runtime: Runtime, job: Job) -> dict:
    runs = runtime.index.list_runs(job.id)
    filesets = runtime.index.list_filesets(job.id)
    payload = job.to_dict()
    payload["retention_description"] = describe_retention(job.retention)
    payload["latest_run"] = runs[0].to_dict() if runs else None
    payload["fileset_count"] = len(filesets)
    payload["latest_fileset"] = filesets[0].to_dict() if filesets else None
    return payload


def app() -> FastAPI:
    """Uvicorn factory entry, unused when the module global is imported."""
    return create_app()


def build_default_app() -> FastAPI:
    return create_app()
