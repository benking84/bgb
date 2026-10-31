from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.parse
import urllib.request

from bgb.googleapi import OAUTH_SCOPES
from bgb.runtime import build_runtime


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("BGB_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="bgb", description="Backup Google Workspace to Cloud Storage"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="HTTP API and, when built, the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8741")))

    run = sub.add_parser("run", help="Run one backup. Used by the Cloud Run job.")
    run.add_argument("--job-id", required=True)
    run.add_argument("--run-id")

    sub.add_parser(
        "run-due", help="Run every job whose cron is due. Cloud Scheduler entrypoint."
    )

    verify = sub.add_parser(
        "verify", help="Download sample volumes and check block hashes"
    )
    verify.add_argument("--job-id", required=True)
    verify.add_argument("--full", action="store_true")

    restore = sub.add_parser("restore", help="Restore one file from a version")
    restore.add_argument("--job-id", required=True)
    restore.add_argument("--fileset", required=True)
    restore.add_argument("--path", required=True)
    restore.add_argument("--dest", required=True)

    rebuild = sub.add_parser("rebuild", help="Rebuild the index from stored volumes")
    rebuild.add_argument("--job-id", required=True)

    prune = sub.add_parser(
        "prune", help="Delete stored objects the index does not reference"
    )
    prune.add_argument("--job-id", required=True)

    delete_job = sub.add_parser(
        "delete-job", help="Delete a job, its index records, and its stored objects"
    )
    delete_job.add_argument("--job-id", required=True)

    oauth = sub.add_parser(
        "oauth-url", help="Print a Google OAuth consent URL for a single user"
    )
    oauth.add_argument("--client-id", required=True)
    oauth.add_argument("--redirect-uri", required=True)

    exchange = sub.add_parser(
        "oauth-exchange", help="Trade an OAuth code for a refresh token secret"
    )
    exchange.add_argument("--client-id", required=True)
    exchange.add_argument("--client-secret", required=True)
    exchange.add_argument("--redirect-uri", required=True)
    exchange.add_argument("--code", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run(build_server(), host=args.host, port=args.port)
        return
    if args.cmd == "oauth-url":
        query = urllib.parse.urlencode(
            {
                "client_id": args.client_id,
                "redirect_uri": args.redirect_uri,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "scope": " ".join(OAUTH_SCOPES),
            }
        )
        print("https://accounts.google.com/o/oauth2/v2/auth?" + query)
        return

    runtime = build_runtime()
    if args.cmd == "run":
        result = runtime.engine.run_backup(args.job_id, args.run_id)
        print(json.dumps(result.to_dict(), indent=2))
        if result.status == "failed":
            sys.exit(1)
        return
    if args.cmd == "run-due":
        results = runtime.run_due()
        print(json.dumps([row.to_dict() for row in results], indent=2))
        if any(row.status == "failed" for row in results):
            sys.exit(1)
        return
    if args.cmd == "verify":
        print(json.dumps(runtime.engine.verify(args.job_id, full=args.full), indent=2))
        return
    if args.cmd == "restore":
        data, _entry = runtime.engine.read_file(args.job_id, args.fileset, args.path)
        dest = os.path.abspath(args.dest)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
        print(dest)
        return
    if args.cmd == "rebuild":
        print(json.dumps(runtime.engine.rebuild(args.job_id), indent=2))
        return
    if args.cmd == "prune":
        print(
            json.dumps({"removed": runtime.engine.prune_orphans(args.job_id)}, indent=2)
        )
        return
    if args.cmd == "delete-job":
        print(json.dumps(runtime.delete_job(args.job_id), indent=2))
        return
    if args.cmd == "oauth-exchange":
        _exchange(runtime, args)
        return
    parser.error(f"unknown command {args.cmd}")


def build_server():
    from bgb.api.app import create_app

    return create_app(build_runtime())


def _exchange(runtime, args) -> None:
    form = urllib.parse.urlencode(
        {
            "code": args.code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": args.redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if "refresh_token" not in payload:
        raise SystemExit(
            "Google did not return a refresh token. Repeat consent with prompt=consent."
        )
    secret = json.dumps(
        {
            "refresh_token": payload["refresh_token"],
            "client_id": args.client_id,
            "client_secret": args.client_secret,
        }
    ).encode()
    settings = runtime.index.get_settings()
    try:
        runtime.secrets.put(settings.oauth_secret, secret)
    except Exception:  # noqa: BLE001 - any store failure falls back to printing the secret for manual upload
        print(secret.decode())
        print(
            f"The secret store refused the write. Add the JSON above as a version of {settings.oauth_secret}.",
            file=sys.stderr,
        )
        return
    print(
        f"Stored the refresh token in {settings.oauth_secret}. Set auth_mode to oauth."
    )


if __name__ == "__main__":
    main()
