#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python3 -m bgb serve --host 127.0.0.1 --port 8741 &
api_pid=$!
trap 'kill $api_pid' EXIT
cd "$root/web"
npm run dev
