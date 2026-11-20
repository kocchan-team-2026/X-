#!/bin/bash
# ボード(アダルト用 + 設定があればエンタメ用)を起動し、アダルト用ボードをブラウザで開く。
# Finder/Spotlight から開いたときは PATH が最小限なので、ffmpeg などの場所を足しておく。
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")/.." || exit 1  # プロジェクト直下へ
PY=".venv/bin/python3"
LOG="$HOME/Library/Logs/xboard.log"
[ -x "$PY" ] || { echo "先に ./scripts/setup.sh を実行してください"; exit 1; }
[ -f .env ] || { echo ".env がありません。先に ./scripts/setup.sh を実行してください"; exit 1; }

envval() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d "\"' "; }
PORT="$(envval GALLERY_PORT)"; PORT="${PORT:-8765}"
PORT_ENT="$(envval GALLERY_PORT_ENT)"; PORT_ENT="${PORT_ENT:-8766}"
USE_ENT="$(envval CHANNEL_IDS_ENT)"

listening() { /usr/sbin/lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
start() { # ポート, 引数
  listening "$1" || nohup "$PY" -m xdeck $2 >> "$LOG" 2>&1 &
}
start "$PORT" ""
[ -n "$USE_ENT" ] && start "$PORT_ENT" "ent"

for p in "$PORT" ${USE_ENT:+$PORT_ENT}; do
  for _ in $(seq 1 30); do listening "$p" && break; sleep 1; done
done
listening "$PORT" || { echo "起動に失敗しました。ログ: $LOG"; exit 1; }
open "http://localhost:$PORT"
