#!/bin/bash
# 初回セットアップ: 仮想環境・依存パッケージ・.env・macOS アプリを用意する。
# 使い方: ./setup.sh            (対話で .env を作り、アプリも作る)
#         ./setup.sh --no-prompt (対話なし。.env は .env.example のコピーだけ作る)
set -e
cd "$(dirname "$0")"
PROMPT=1; [ "$1" = "--no-prompt" ] && PROMPT=0

echo "== 1/4 Python 環境 =="
PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || { echo "python3 が見つかりません。https://www.python.org/ または 'brew install python' で入れてください"; exit 1; }
"$PYBIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10 以上が必要です($("$PYBIN" --version))"; exit 1; }
[ -d .venv ] || "$PYBIN" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "OK"

echo "== 2/4 外部ツールの確認 =="
for t in ffmpeg ffprobe; do
  if command -v $t >/dev/null || [ -x /usr/local/bin/$t ] || [ -x /opt/homebrew/bin/$t ]; then echo "$t: OK"
  else echo "$t: 見つかりません → 'brew install ffmpeg' で入れてください(動画の加工に必要)"; fi
done
if command -v claude >/dev/null; then echo "claude (Claude Code): OK"
else echo "claude: 見つかりません(任意。本文リライト機能だけに使います)"; fi
[ -d /Applications/XDeck.app ] && echo "Xdeck: OK" || echo "Xdeck: /Applications に見つかりません(投稿・インプ取得に必要です)"

echo "== 3/4 .env =="
if [ -f .env ]; then
  echo ".env は既にあります(変更しません)"
else
  cp .env.example .env
  if [ "$PROMPT" = 1 ]; then
    set_kv() { # キー 値  (値は sed を使わず python で安全に書き込む)
      .venv/bin/python3 - "$1" "$2" <<'PY'
import sys, re
k, v = sys.argv[1], sys.argv[2]
s = open(".env", encoding="utf-8").read()
s = re.sub(rf"^{k}=.*$", lambda m: f"{k}={v}", s, count=1, flags=re.M)
open(".env", "w", encoding="utf-8").write(s)
PY
    }
    read -r -s -p "Discord Bot のトークン(入力は表示されません): " v; echo; [ -n "$v" ] && set_kv DISCORD_BOT_TOKEN "$v"
    read -r -s -p "Xdeck の API トークン(入力は表示されません): " v; echo; [ -n "$v" ] && set_kv XDECK_TOKEN "$v"
    read -r -p "普通用の Discord チャンネルID(カンマ区切り。空=エンタメ用以外の全チャンネル): " v; [ -n "$v" ] && set_kv CHANNEL_IDS "$v"
    read -r -p "エンタメ用の Discord チャンネルID(空=エンタメ用ボードを使わない): " v; [ -n "$v" ] && set_kv CHANNEL_IDS_ENT "$v"
    chmod 600 .env
    echo ".env を作りました"
  else
    chmod 600 .env
    echo ".env を作りました。トークンなどを自分で書き込んでください"
  fi
fi
grep -qE '^DISCORD_BOT_TOKEN=.+' .env || echo "⚠ .env の DISCORD_BOT_TOKEN が空です"
grep -qE '^XDECK_TOKEN=.+' .env || echo "⚠ .env の XDECK_TOKEN が空です"

echo "== 4/4 macOS アプリ =="
if [ "$(uname)" = Darwin ]; then
  chmod +x start.sh make_app.sh
  ./make_app.sh
else
  echo "macOS 以外では、./start.sh でボードを起動してください"
fi
echo
echo "完了です。「Xdeck補助」アプリ(または ./start.sh)を開くとボードが開きます。詳しくは README.md を見てください。"
