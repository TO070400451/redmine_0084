#!/usr/bin/env bash
# 1回実行スクリプト
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if [ ! -f .env ]; then
    echo "ERROR: .env が見つかりません。.env.example をコピーして設定してください。"
    exit 1
fi

python -m src.main --once "$@"
