#!/usr/bin/env bash
# Runs the Python research service (backend/) and the Next.js app together.
set -e
cd "$(dirname "$0")"
trap 'kill 0' EXIT
(cd backend && python3 web.py) &
npx next dev
