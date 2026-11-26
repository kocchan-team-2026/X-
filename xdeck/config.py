"""設定・定数・データの保存先。ほかのモジュールはここだけを見て設定を知る。

ボード種別は起動引数で決まる: `python -m xdeck` = アダルト用 / `python -m xdeck ent` = エンタメ用。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """プロジェクト直下の .env を読む。`KEY=VALUE` 形式でも、トークンだけの1行でもOK。"""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and re.match(r"^[A-Z_][A-Z0-9_]*=", line):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
        else:
            os.environ.setdefault("DISCORD_BOT_TOKEN", line.strip("\"'"))


def _ids(key: str) -> set[int]:
    return {int(x) for x in os.environ.get(key, "").split(",") if x.strip()}


load_env()
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

# ---- ボード種別 ----
ENT = len(sys.argv) > 1 and sys.argv[1] == "ent"
FORTUNE = len(sys.argv) > 1 and sys.argv[1] == "uranai"  # 占い用ボード(アフィリエイト案件: A8 のココナラ電話占い)
BOARD_NAME = "占い" if FORTUNE else ("エンタメ" if ENT else "アダルト")
BOOST_WORD = "ブースト"  # グループ名にこれを含むアカウントは投稿対象外(アダルト用・エンタメ用とも)
ADULT_GROUPS = tuple(g.strip() for g in os.environ.get("ADULT_GROUPS", "投稿").split(",") if g.strip())  # アダルト用ボードで使うグループ(名前が完全一致するものだけ)
ENT_WORD = "エンタメ"  # グループ名にこれを含むアカウントはエンタメ用
FORTUNE_WORD = "占い"  # グループ名にこれを含むアカウントは占い用(アダルト用・エンタメ用のボードからは投稿・予約の対象外)

ENT_CHANNELS = _ids("CHANNEL_IDS_ENT")
FORTUNE_CHANNELS = _ids("CHANNEL_IDS_URANAI")
CHANNEL_IDS = FORTUNE_CHANNELS if FORTUNE else (ENT_CHANNELS if ENT else _ids("CHANNEL_IDS"))  # アダルト用が空なら全チャンネル(エンタメ用チャンネルは除く)

# ---- データの保存先 ----
#   data/<adult|ent>/posts/  保存した投稿(動画・画像・本文)
#   data/<adult|ent>/state/  予約・履歴・自動リプの状態・アイコンなどの管理データ
DATA_ROOT = Path(os.environ.get("DATA_DIR", ROOT / "data"))
_BOARD_DIR = "uranai" if FORTUNE else ("ent" if ENT else "adult")
POSTS_DIR = DATA_ROOT / _BOARD_DIR / "posts"
STATE_DIR = DATA_ROOT / _BOARD_DIR / "state"
ADULT_STATE_DIR = DATA_ROOT / "adult" / "state"  # エンタメ用がアダルト用の投稿履歴を読むため
WORKS_DIR = STATE_DIR / "_works"

# ---- ポート ----
PORT_ADULT = os.environ.get("GALLERY_PORT", "8765")
PORT_ENT = os.environ.get("GALLERY_PORT_ENT", "8766")
PORT_FORTUNE = os.environ.get("GALLERY_PORT_URANAI", "8767")
PORT = int(PORT_FORTUNE if FORTUNE else (PORT_ENT if ENT else PORT_ADULT))
GALLERY_URL = f"http://localhost:{PORT}"

# ---- Discord ----
DISCORD_URL = os.environ.get("DISCORD_URL", "")  # サイドバーの「Discordを開く」の飛び先。空なら Bot が見ているサーバー/チャンネルから自動で作る

NOTIFY_CHANNEL_ID = int(os.environ.get("NOTIFY_CHANNEL_ID", "0") or 0)  # 投稿の失敗などを通知する Discord チャンネルID(空なら、Bot が見ているチャンネル)

# ---- DMM(FANZA)アフィリエイト: URLからアフィリエイトリンクを自動で作る ----
DMM_API_ID = os.environ.get("DMM_API_ID", "")
DMM_AFFILIATE_ID = os.environ.get("DMM_AFFILIATE_ID", "")  # 例: xxxx-990

# ---- Xdeck ----
XDECK_URL = os.environ.get("XDECK_URL", "http://127.0.0.1:39150/api/v1")
XDECK_TOKEN = os.environ.get("XDECK_TOKEN", "")

# ---- 機能ごとの設定 ----
IMP_TARGET = int(os.environ.get("IMP_TARGET", "2500"))  # このインプ数に達したら Xdeck が通知する
SCHED_GRACE_MIN = 30  # 予約時刻をこれ以上過ぎていたら(Bot停止中など)投稿せず「見送り」にする

FOLLOWUP_ON = os.environ.get("FOLLOWUP", "1") != "0"                       # 0 で自動リプを止める
FOLLOWUP_TEXT = os.environ.get("FOLLOWUP_TEXT", "続きです〜")                  # アダルト用: リプの本文(この後ろにリンク)
FOLLOWUP_TEXT_ENT = os.environ.get("FOLLOWUP_TEXT_ENT", "おすすめです〜")      # エンタメ用:1つ目のリプ本文
FOLLOWUP_TEXT_URANAI = os.environ.get("FOLLOWUP_TEXT_URANAI", "続きです〜\n※広告を含みます【PR】")  # 占い用: 1つ目のリプ本文(この後ろにアフィリエイトリンク)
RECOMMEND_N = int(os.environ.get("RECOMMEND_N", "3"))                      # おすすめとして貼るアダルト用投稿の数
LIKE_TARGET = int(os.environ.get("LIKE_TARGET", "40"))  # このいいね数に達しても、インプ達成と同じく自動リプする(0で無効)
LIKE_WINDOW_H = 48       # いいねを確認するのは、投稿からこの時間以内のもの
LIKE_CHECK_MIN = 15      # いいねの確認間隔(分)
FOLLOWUP_WINDOW_H = 24   # 到達後これを過ぎたらリンク未登録でも諦める
FOLLOWUP_MAX_TRIES = 3

# ---- 正規表現・作品サイト ----
URL_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w+)/status/(\d+)")
ANY_URL_RE = re.compile(r"https?://[^\s<>]+")
WORK_SITES = [  # 作品URLとして扱うサービス (ドメイン末尾一致)
    ("MyFans", ("myfans.jp",)),
    ("FANZA", ("dmm.co.jp", "dmm.com", "fanza.com")),
]


def group_ok(group: str) -> bool:
    """このボードから投稿してよいグループか"""
    if BOOST_WORD in group:  # ブースト用グループは、どのボードの投稿対象外
        return False
    if FORTUNE:
        return FORTUNE_WORD in group
    if FORTUNE_WORD in group:  # 占い用グループは、アダルト用・エンタメ用の投稿対象外
        return False
    if ENT:
        return ENT_WORD in group
    return group.strip() in ADULT_GROUPS  # アダルト用: 「投稿」グループだけ(シャドウバン中・toB・栽培中・アダルト２などは対象外)
