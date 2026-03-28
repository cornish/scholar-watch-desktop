#!/bin/bash
set -e

REPO=/home/cornish/scholar-watch
VENV=$REPO/.venv

echo "==> Pulling latest code"
git -C "$REPO" pull origin main

echo "==> Installing dependencies"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt"
"$VENV/bin/pip" install -q -e "$REPO"

echo "==> Running migrations"
cd "$REPO" && "$VENV/bin/alembic" upgrade head

echo "==> Restarting service"
sudo systemctl restart scholar-watch

echo "==> Deploy complete"
echo "    Dashboard: http://127.0.0.1:9743"
