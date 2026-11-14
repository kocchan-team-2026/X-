"""Discord に投げた X(Twitter) のリンクを検知し、本文・画像・動画をローカル保存する Bot。
動画は保存後に macOS のクリップボードへファイルとしてコピーする (Cmd+V で貼り付け可能)。
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import discord
import requests
from aiohttp import web

def load_env() -> None:
    """同じフォルダの .env を読む。`KEY=VALUE` 形式でも、トークンだけの1行でもOK。"""
    f = Path(__file__).parent / ".env"
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


load_env()
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
# ボード種別: `python bot.py` = 普通用 / `python bot.py ent` = エンタメ用
ENT = len(sys.argv) > 1 and sys.argv[1] == "ent"
BOARD_NAME = "エンタメ" if ENT else "普通"
ENT_WORD = "エンタメ"  # グループ名にこれを含むアカウントはエンタメ用


def _ids(key: str) -> set[int]:
    return {int(x) for x in os.environ.get(key, "").split(",") if x.strip()}


ENT_CHANNELS = _ids("CHANNEL_IDS_ENT")
if ENT:
    SAVE_DIR = Path(os.environ.get("SAVE_DIR_ENT", Path(__file__).parent / "saved_ent"))
    CHANNEL_IDS = ENT_CHANNELS
    if not CHANNEL_IDS:
        sys.exit("エンタメ用ボードには .env に CHANNEL_IDS_ENT=<チャンネルID> が必要です")
else:
    SAVE_DIR = Path(os.environ.get("SAVE_DIR", Path(__file__).parent / "saved"))
    # 空なら全チャンネル(エンタメ用チャンネルは除く)
    CHANNEL_IDS = _ids("CHANNEL_IDS")


def group_ok(group: str) -> bool:
    """このボードから投稿してよいグループか"""
    return (ENT_WORD in group) == ENT

URL_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w+)/status/(\d+)")


# 作品URLとして扱うサービス (ドメイン末尾一致)
WORK_SITES = [
    ("MyFans", ("myfans.jp",)),
    ("FANZA", ("dmm.co.jp", "dmm.com", "fanza.com")),
]
ANY_URL_RE = re.compile(r"https?://[^\s<>]+")
WORKS_DIR = SAVE_DIR / "_works"


def find_work_urls(text: str) -> list[dict]:
    from urllib.parse import urlparse
    found = []
    for u in ANY_URL_RE.findall(text):
        u = u.rstrip(").,」』>")
        host = (urlparse(u).hostname or "").lower()
        for label, domains in WORK_SITES:
            if any(host == d or host.endswith("." + d) for d in domains):
                found.append({"url": u, "site": label})
                break
    return found


def add_work_urls(work_id: str, urls: list[dict]) -> list[dict]:
    """作品に紐づくURLを保存。すでにあるURLは除き、新規分だけ返す。"""
    WORKS_DIR.mkdir(parents=True, exist_ok=True)
    f = WORKS_DIR / f"{work_id}.json"
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"urls": []}
    have = {x["url"] for x in data["urls"]}
    new = [x for x in urls if x["url"] not in have]
    for x in new:
        x["added_at"] = datetime.now().isoformat(timespec="seconds")
    data["urls"] += new
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return new


XDECK_URL = os.environ.get("XDECK_URL", "http://127.0.0.1:39150/api/v1")
XDECK_TOKEN = os.environ.get("XDECK_TOKEN", "")


def xdeck(method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{XDECK_URL}/{path}", headers={"X-Api-Token": XDECK_TOKEN},
                         timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r.json()


def rewrite_text(text: str, urls: list[str] | None = None) -> list[str]:
    """Claude Code (claude -p) で本文を強めにリライトし、書き方の違う3案を返す。リンクは本文に含めない。"""
    import random
    body = re.sub(r"https?://\S+", "", text).strip()
    if not body:
        return [text]
    angles = random.sample([
        "語順を入れ替え、文の組み立てを大きく変える",
        "言い切りの短い文にまとめ直す",
        "問いかけや呼びかけの形に変える",
        "口語・話し言葉をより強くして言い換える",
        "体言止めや倒置を使って言い換える",
        "文末表現と接続の仕方をすべて変える",
    ], 3)
    prompt = (
        "次のX(Twitter)投稿の本文を、意味と元の口調・テンションは保ったまま、強めにリライトしてください。\n"
        "元の文とは、語句・語順・文末をはっきり変え、別の文章に見えるレベルで書き直します。\n"
        "ただし次を守ること:\n"
        "- 事実や固有名詞(人名・作品名)は変えない・足さない\n"
        "- ハッシュタグと@メンションはそのまま残す\n"
        "- 元より長くしない。絵文字は元の雰囲気の範囲で\n"
        "- URLは本文に含まれていないので、書かない\n\n"
        "3案を作ります。案ごとに次の方針で書き分けてください:\n"
        + "\n".join(f"案{i + 1}: {a}" for i, a in enumerate(angles))
        + "\n\n出力は、3つの文字列からなるJSON配列のみ。説明や前置きは一切書かない。\n"
        f"【元の文】\n{body}\n"
    )
    res = subprocess.run(["claude", "-p", prompt, "--tools", ""], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=180, cwd=str(Path(__file__).parent / "saved"))
    out = res.stdout.strip()
    if res.returncode != 0 or not out:
        raise RuntimeError(res.stderr.strip() or "リライトに失敗しました")
    try:
        cands = json.loads(out[out.index("["): out.rindex("]") + 1])
        cands = [c.strip() for c in cands if isinstance(c, str) and c.strip()]
    except Exception:  # noqa: BLE001
        cands = [out]  # JSONで返らなかったときは、全体を1案として扱う
    if not cands:
        raise RuntimeError("リライト結果が空でした")
    # 本文にリンクは入れない(元の文にURLがあっても外す)
    return [re.sub(r"\s*https?://\S+", "", c).strip() for c in cands]


def video_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return float(r.stdout.strip())


def edit_video(src: Path, dest: Path, crop: float, brightness: float, contrast: float, saturation: float,
               head: float = 0.0, tail: float = 0.0) -> None:
    """四辺を crop(0〜0.1 の割合)ずつ切り抜き、明るさ・コントラスト・彩度を調整し、前後を head/tail 秒カットして再エンコード。"""
    crop = min(max(crop, 0.0), 0.10)
    keep = 1 - 2 * crop
    vf = (f"crop=trunc(iw*{keep:.4f}/2)*2:trunc(ih*{keep:.4f}/2)*2,"
          f"eq=brightness={min(max(brightness, -0.3), 0.3):.3f}:contrast={min(max(contrast, 0.5), 2.0):.3f}"
          f":saturation={min(max(saturation, 0.0), 3.0):.3f}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    trim = []
    if head > 0 or tail > 0:
        dur = video_duration(src)
        if dur - head - tail >= 1.0:  # 短すぎる動画は秒数カットしない
            trim = ["-ss", f"{head:.3f}", "-t", f"{dur - head - tail:.3f}"]
    cmd = ["ffmpeg", "-y", "-i", str(src), *trim, "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip().splitlines()[-1] if res.stderr else "ffmpeg failed")


def make_thumb(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for ss in ("0.5", "0"):
        r = subprocess.run(["ffmpeg", "-y", "-ss", ss, "-i", str(src), "-frames:v", "1", "-vf", "scale=640:-2", str(dest)],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        if r.returncode == 0 and dest.exists():
            return
    raise RuntimeError("thumbnail failed")


def copy_file_to_clipboard(path: Path) -> None:
    """Finder でコピーしたのと同じ状態にする。"""
    script = f'set the clipboard to (POSIX file "{path.resolve()}")'
    subprocess.run(["osascript", "-e", script], check=True)


def download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def already_saved(work_id: str, tweet_id: str) -> bool:
    for meta in SAVE_DIR.glob("*/meta.json"):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if m.get("work_id") == work_id and m.get("tweet_id") == tweet_id:
            return True
    return False


def save_tweet(user: str, tweet_id: str, work_id: str, src: dict | None = None) -> tuple[Path, list[Path], dict]:
    res = requests.get(f"https://api.fxtwitter.com/{user}/status/{tweet_id}", timeout=30)
    res.raise_for_status()
    tw = res.json()["tweet"]

    folder = SAVE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tw['author']['screen_name']}_{tweet_id}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "meta.json").write_text(json.dumps({
        "work_id": work_id, "tweet_id": tweet_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        **({"discord": src} if src else {}),  # どのDiscordメッセージ/スレッドから来たか(確認用)
    }), encoding="utf-8")
    (folder / "tweet.json").write_text(json.dumps(tw, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "text.md").write_text(
        f"# {tw['author']['name']} (@{tw['author']['screen_name']})\n\n"
        f"{tw['text']}\n\n{tw['url']}\n",
        encoding="utf-8",
    )

    videos: list[Path] = []
    media = tw.get("media") or {}
    for i, p in enumerate(media.get("photos", []), 1):
        ext = Path(p["url"].split("?")[0]).suffix or ".jpg"
        download(p["url"], folder / f"image_{i}{ext}")
    for i, v in enumerate(media.get("videos", []), 1):
        dest = folder / f"video_{i}.mp4"
        download(v["url"], dest)
        videos.append(dest)
    return folder, videos, tw


PORT = int(os.environ.get("GALLERY_PORT_ENT", "8766")) if ENT else int(os.environ.get("GALLERY_PORT", "8765"))
GALLERY_URL = f"http://localhost:{PORT}"

def page() -> str:
    html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
    html = html.replace("__BN__", "(エンタメ)" if ENT else "")
    pn = os.environ.get("GALLERY_PORT", "8765")
    pe = os.environ.get("GALLERY_PORT_ENT", "8766")
    cur = 'aria-current="page"'
    return (html.replace("__P_N__", pn).replace("__P_E__", pe)
            .replace("__A_N__", "" if ENT else cur).replace("__A_E__", cur if ENT else ""))


def list_items():
    """保存済みの投稿を、Discord スレッド(作品)ごとにまとめて返す。新しい作品が先頭。"""
    works: dict[str, dict] = {}
    for d in sorted((p for p in SAVE_DIR.glob("*") if p.is_dir())):
        try:
            tw = json.loads((d / "tweet.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
        wid = meta.get("work_id") or d.name
        files = sorted(f.name for f in d.iterdir())
        saved_at = meta.get("saved_at")
        if not saved_at:
            try:
                saved_at = datetime.strptime(d.name[:15], "%Y%m%d_%H%M%S").isoformat(timespec="seconds")
            except ValueError:
                saved_at = datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds")
        post = {
            "saved_at": saved_at,
            "discord": meta.get("discord"),
            "id": d.name,
            "author": f"{tw['author']['name']} (@{tw['author']['screen_name']})",
            "text": tw.get("text", ""),
            "url": tw.get("url", ""),
            "videos": [f for f in files if f.endswith(".mp4")],
            "images": [f for f in files if f.startswith("image_")],
        }
        works.setdefault(wid, {"work_id": wid, "latest": d.name, "posts": []})
        works[wid]["posts"].append(post)
        works[wid]["latest"] = d.name
    for f in WORKS_DIR.glob("*.json") if WORKS_DIR.exists() else []:
        try:
            urls = json.loads(f.read_text(encoding="utf-8"))["urls"]
        except Exception:  # noqa: BLE001
            continue
        w = works.setdefault(f.stem, {"work_id": f.stem, "latest": "", "posts": []})
        w["urls"] = urls
        w["latest"] = max(w["latest"], datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y%m%d_%H%M%S"))
    for w in works.values():
        w.setdefault("urls", [])
        times = [p["saved_at"] for p in w["posts"]] + [u.get("added_at", "") for u in w["urls"]]
        times = [t for t in times if t]
        w["created_at"], w["updated_at"] = (min(times), max(times)) if times else ("", "")
    return sorted(works.values(), key=lambda w: w["updated_at"] or w["latest"], reverse=True)


def safe_path(item_id: str, name: str) -> Path:
    p = (SAVE_DIR / item_id / name).resolve()
    if SAVE_DIR.resolve() not in p.parents or not p.is_file():
        raise web.HTTPNotFound()
    return p


SCHED_LOCK = asyncio.Lock()
SCHED_GRACE_MIN = 30  # 予約時刻をこれ以上過ぎていたら(Bot停止中など)投稿せず「見送り」にする


def sched_file() -> Path:
    return SAVE_DIR / "_schedule.json"


def load_sched() -> list[dict]:
    f = sched_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_sched(items: list[dict]) -> None:
    tmp = sched_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(sched_file())


async def send_post(work_id: str, profile_id: str, text: str, paths: list[str]) -> dict:
    payload = {"kind": "post", "profile_ids": [profile_id], "text": text}
    if paths:
        payload["media_paths"] = paths
    log = {"at": datetime.now().isoformat(timespec="seconds"), "work_id": work_id, "profile_id": profile_id,
           "text": text, "media": paths}

    def write_log(extra):
        with open(SAVE_DIR / "_posts.log", "a", encoding="utf-8") as lf:
            lf.write(json.dumps({**log, **extra}, ensure_ascii=False) + "\n")

    write_log({"event": "request"})  # 先に記録(失敗しても何を送ったか残る)
    # Xdeck は投稿完了まで応答を返さないことがある(30秒前後)ので長めに待つ
    res = await asyncio.to_thread(xdeck, "POST", "x/bulk", json=payload, timeout=300)
    write_log({"event": "response", "response": res})
    return res


async def add_sched(work_id: str, profile_id: str, pname: str, text: str, paths: list[str], at: datetime,
                    extra: dict | None = None) -> dict:
    sid = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(3).hex()
    # 加工済み動画は後から作り直されても変わらないよう、予約時点のコピーを保持する
    snap = SAVE_DIR / "_sched" / sid
    snap.mkdir(parents=True, exist_ok=True)
    kept = []
    for src in paths:
        dst = snap / Path(src).name
        await asyncio.to_thread(shutil.copy2, src, dst)
        kept.append(str(dst))
    e = {"id": sid, "at": at.isoformat(timespec="minutes"), "status": "pending",
         "work_id": work_id, "profile_id": profile_id, "profile_name": pname,
         "text": text, "media": kept, "created": datetime.now().isoformat(timespec="seconds"), **(extra or {})}
    async with SCHED_LOCK:
        items = load_sched()
        items.append(e)
        save_sched(items)
    return e


def get_profiles() -> list[dict]:
    prof = xdeck("GET", "profile/list")["data"]["list"]
    gname = {g["group_id"]: g["name"] for g in xdeck("GET", "group/list")["data"]["list"]}
    return [{"id": x["profile_id"], "name": x["name"], "group": gname.get(x["group_id"], "")} for x in prof]


def posted_pairs() -> set[tuple[str, str]]:
    """(work_id, profile_id): すでに投稿済み、または予約済みの組み合わせ"""
    out = {(x["work_id"], x["profile_id"]) for x in load_sched() if x["status"] in ("pending", "running", "done")}
    f = SAVE_DIR / "_posts.log"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if e.get("event") == "response" and (e.get("response") or {}).get("code") == 0:
                out.add((e.get("work_id", ""), e.get("profile_id", "")))
    return out


def last_posts() -> dict[str, str]:
    """アカウントごとの前回投稿日時(このボードから投稿した分)。ISO文字列"""
    out: dict[str, str] = {}

    def upd(pid: str, at: str) -> None:
        if pid and at and at > out.get(pid, ""):
            out[pid] = at

    f = SAVE_DIR / "_posts.log"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if e.get("event") == "response" and (e.get("response") or {}).get("code") == 0:
                upd(e.get("profile_id", ""), e.get("at", ""))
    for x in load_sched():
        if x["status"] == "done":
            upd(x["profile_id"], x.get("finished") or x["at"])
    return out


SB_FILE = lambda: SAVE_DIR / "_shadowban.json"  # noqa: E731
SB_JOBS: dict[str, dict] = {}
SB_LOCK = asyncio.Lock()


def sb_load() -> dict:
    f = SB_FILE()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def sb_summary(r: dict) -> dict:
    """Xdeck の判定結果から、ボードで使う要点を取り出す。
    🟡注意 = 検索デブースト・メディア制限・センシティブ・ログアウトで非表示 のどれか(理由を文字で併記)。
    検索を使う判定(検索BAN・検索デブースト・メディア制限)は、検索が1回も実行されていないと
    確証がないので「(未検証)」と明記する"""
    c = r.get("checks") or {}
    ran = ((r.get("diagnostics") or {}).get("searchRequests") or 0) > 0
    search_based = {"searchBan", "searchDeboost", "mediaBan"}
    names = {"searchBan": "検索BAN", "searchDeboost": "検索デブースト", "mediaBan": "メディア制限",
             "sensitive": "センシティブ判定", "hiddenWhenLoggedOut": "ログアウトで非表示",
             "suspended": "凍結", "locked": "ロック", "notFound": "見つからない"}
    posts = r.get("posts") or []
    tested = [x for x in posts if x.get("foundBySearch") is not None]
    missed = [x for x in tested if x.get("foundBySearch") is False]
    reasons, hard = [], False
    for k, label in names.items():
        if not c.get(k):
            continue
        extra = []
        if k in search_based and not ran:
            extra.append("未検証")
        if k == "searchDeboost" and tested:
            extra.append(f"検索に出ない{len(missed)}/{len(tested)}件")
        reasons.append(label + (f"({'・'.join(extra)})" if extra else ""))
        if k in ("suspended", "locked", "notFound") or (k == "searchBan" and ran):
            hard = True
    note = "" if ran else "検索が実行されていない(検索系の判定は未検証)"
    if r.get("error"):
        level, label, note = "unknown", "判定不能", str(r.get("error"))[:120]
    elif hard:
        level, label = "bad", "規制の疑い"
    elif reasons:
        level, label = "warn", "注意"
    elif not ran:
        level, label = "unknown", "判定不能"  # 検索が実行されていないので「問題なし」とも言えない
    else:
        level, label = "ok", "問題なし"
    return {"level": level, "label": label, "verdict": r.get("verdict"),
            "flags": reasons, "score": (r.get("score") or {}).get("total"),
            "error": note, "search_requests": (r.get("diagnostics") or {}).get("searchRequests"),
            "checked_at": datetime.now().isoformat(timespec="seconds")}


async def run_shadowban(job: str, profile_ids: list[str]) -> None:
    st = SB_JOBS[job]
    try:
        for pid in profile_ids:
            try:
                info = (await asyncio.to_thread(xdeck, "GET", "x/get", params={"profile_id": pid}))["data"]["profile"]
                res = await asyncio.to_thread(xdeck, "GET", "x/shadowban", params={"screen_name": info["screenName"]}, timeout=180)
                if res.get("code") != 0:
                    raise RuntimeError(res.get("msg") or "failed")
                summ = sb_summary(res["data"])
            except Exception as e:  # noqa: BLE001
                summ = {"level": "unknown", "label": "判定不能", "verdict": None, "flags": [], "score": None,
                        "error": str(e)[:120], "checked_at": datetime.now().isoformat(timespec="seconds")}
            async with SB_LOCK:
                d = sb_load()
                d[pid] = summ
                SB_FILE().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            st["done"] += 1
        st["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        st["state"] = "error"
        st["error"] = str(e)[:200]


BULK: dict[str, dict] = {}


def pick_media(work: dict):
    """作品から添付を1つ選ぶ。動画があれば動画をランダムで1本、なければ画像(最大4枚)"""
    import random
    vids = [(p["id"], v) for p in work["posts"] for v in p["videos"]]
    if vids:
        pid, v = random.choice(vids)
        return next(p for p in work["posts"] if p["id"] == pid), [(pid, v, "v")]
    for p in work["posts"]:
        if p["images"]:
            return p, [(p["id"], i, "i") for i in p["images"][:4]]
    return None, []


async def prep_one(work: dict, profile: dict, at: datetime, batch: str) -> dict:
    """1件分: 本文リライト + 動画加工 + 予約登録"""
    import random
    post, media = pick_media(work)
    if not media:
        raise RuntimeError("動画も画像もない作品です")
    base = re.sub(r"\s*https?://\S+", "", post["text"]).strip()
    text = base
    if base:
        try:
            cands = await asyncio.to_thread(rewrite_text, base)
            text = random.choice(cands) if cands else base
        except Exception:  # noqa: BLE001
            text = base  # リライトに失敗したら元の文のまま
    if not text:
        raise RuntimeError("本文が空です")
    paths = []
    for pid, name, kind in media:
        src = SAVE_DIR / pid / name
        if kind == "v":
            dest = src.parent / "_edited" / src.name
            u = random.uniform
            lo, hi = 0.1, 0.5
            async with EDIT_LOCK:  # 同じ動画の _edited を同時に書かないように
                await asyncio.to_thread(edit_video, src, dest, 0.02, round(u(0.02, 0.08), 3), round(u(1.05, 1.15), 3),
                                        1.15, round(u(lo, hi), 2), round(u(lo, hi), 2))
                kept = await add_sched(work["work_id"], profile["id"], profile["name"], text, [str(dest)], at,
                                       {"bulk": batch})
            return kept
        paths.append(str(src))
    return await add_sched(work["work_id"], profile["id"], profile["name"], text, paths, at, {"bulk": batch})


EDIT_LOCK = asyncio.Lock()


async def run_bulk(job: str, profile_ids: list[str], start: datetime, end: datetime, per: int) -> None:
    import random
    st = BULK[job]
    try:
        profs = {p["id"]: p for p in await asyncio.to_thread(get_profiles)}
        chosen = [profs[i] for i in profile_ids if i in profs and group_ok(profs[i]["group"])]
        works = [w for w in await asyncio.to_thread(list_items) if pick_media(w)[1]]
        used = posted_pairs()
        usage: dict[str, int] = {w["work_id"]: 0 for w in works}
        plan = []
        for pr in chosen:
            elig = [w for w in works if (w["work_id"], pr["id"]) not in used]
            random.shuffle(elig)
            elig.sort(key=lambda w: usage[w["work_id"]])  # まだ使われていない作品を優先
            pick = elig[:per]
            if len(pick) < per:
                st["notes"].append(f"{pr['name']}: 投稿できる作品が{len(pick)}件しかありません")
            span = max((end - start).total_seconds(), 60)
            # 窓の中で等間隔に区切り、各区間内でランダムに選ぶ(同じ時刻に固まりにくい)
            for i, w in enumerate(pick):
                seg = span / max(len(pick), 1)
                t = start + timedelta(seconds=seg * i + random.uniform(0, seg))
                plan.append((w, pr, t.replace(second=0, microsecond=0)))
                usage[w["work_id"]] += 1
        st["total"] = len(plan)
        sem = asyncio.Semaphore(2)

        async def one(w, pr, t):
            async with sem:
                try:
                    await prep_one(w, pr, t, job)
                except Exception as e:  # noqa: BLE001
                    st["errors"].append(f"{pr['name']}: {str(e)[:120]}")
                st["done"] += 1

        await asyncio.gather(*(one(*x) for x in plan))
        st["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        st["state"] = "error"
        st["errors"].append(str(e)[:200])


IMP_TARGET = int(os.environ.get("IMP_TARGET", "5000"))  # このインプ数に達したら Xdeck が通知する


def register_imp_alert(url: str) -> bool:
    """投稿を Xdeck のインプ達成通知に登録する(失敗しても投稿には影響させない)"""
    try:
        r = xdeck("POST", "imp-alerts/create", json={
            "tweet": url, "url": url, "target": IMP_TARGET, "target_views": IMP_TARGET, "targetViews": IMP_TARGET})
        return r.get("code") == 0
    except Exception as e:  # noqa: BLE001
        print("imp alert error:", e)
        return False


async def run_due_posts() -> None:
    now = datetime.now()
    async with SCHED_LOCK:
        items = load_sched()
        due = [x for x in items if x["status"] == "pending" and datetime.fromisoformat(x["at"]) <= now]
        for x in due:
            if now - datetime.fromisoformat(x["at"]) > timedelta(minutes=SCHED_GRACE_MIN):
                x["status"] = "missed"
            else:
                x["status"] = "running"
        if due:
            save_sched(items)
    for x in [d for d in due if d["status"] == "running"]:
        result: dict = {}
        try:
            res = await send_post(x["work_id"], x["profile_id"], x["text"], x["media"])
            if res.get("code") != 0:
                raise RuntimeError(res.get("msg") or str(res))
            jid = (res.get("data") or {}).get("job_id")
            job = {}
            for _ in range(30):
                job = ((await asyncio.to_thread(xdeck, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})).get("data")) or {}
                if str(job.get("state")).lower() in ("done", "failed", "error", "finished", "completed"):
                    break
                await asyncio.sleep(2)
            if job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error"):
                raise RuntimeError(job.get("error") or "Xdeck 側で投稿に失敗しました")
            label = ((job.get("steps") or [{}])[0].get("label") or "").replace("@", "")
            if label and job.get("tweet_id"):
                result["link"] = f"https://x.com/{label}/status/{job['tweet_id']}"
                result["imp_alert"] = await asyncio.to_thread(register_imp_alert, result["link"])
            status = "done"
        except Exception as e:  # noqa: BLE001
            status, result["error"] = "failed", str(e)[:300]
        async with SCHED_LOCK:
            items = load_sched()
            for y in items:
                if y["id"] == x["id"]:
                    y.update(result, status=status, finished=datetime.now().isoformat(timespec="seconds"))
            save_sched(items)
        if status == "done":
            shutil.rmtree(SAVE_DIR / "_sched" / x["id"], ignore_errors=True)


async def scheduler_loop() -> None:
    while True:
        try:
            await run_due_posts()
        except Exception as e:  # noqa: BLE001
            print("scheduler error:", e)
        await asyncio.sleep(20)


async def start_web():
    import asyncio

    async def index(_):
        return web.Response(text=page(), content_type="text/html")

    async def api_items(_):
        return web.json_response(list_items())

    async def files(req):
        return web.FileResponse(safe_path(req.match_info["id"], req.match_info["name"]))

    async def copy_file(req):
        p = safe_path(req.match_info["id"], req.match_info["name"])
        await asyncio.to_thread(copy_file_to_clipboard, p)
        return web.Response(text="ok")

    async def copy_text(req):
        p = safe_path(req.match_info["id"], "tweet.json")
        text = json.loads(p.read_text(encoding="utf-8"))["text"]
        await asyncio.to_thread(
            lambda: subprocess.run(["pbcopy"], input=text.encode(), check=True))
        return web.Response(text="ok")

    async def copy_url(req):
        # 保存済みの作品URLだけコピー可 (任意文字列は受け付けない)
        wid, url = req.match_info["id"], req.match_info["url"]
        f = WORKS_DIR / f"{wid}.json"
        if "/" in wid or not f.exists() or url not in {x["url"] for x in json.loads(f.read_text(encoding="utf-8"))["urls"]}:
            raise web.HTTPNotFound()
        await asyncio.to_thread(lambda: subprocess.run(["pbcopy"], input=url.encode(), check=True))
        return web.Response(text="ok")

    async def api_profiles(_):
        prof = (await asyncio.to_thread(xdeck, "GET", "profile/list"))["data"]["list"]
        groups = (await asyncio.to_thread(xdeck, "GET", "group/list"))["data"]["list"]
        gname = {g["group_id"]: g["name"] for g in groups}
        last = await asyncio.to_thread(last_posts)
        sb = await asyncio.to_thread(sb_load)
        nxt: dict[str, list[str]] = {}
        for x in await asyncio.to_thread(load_sched):
            if x["status"] in ("pending", "running"):
                nxt.setdefault(x["profile_id"], []).append(x["at"])
        return web.json_response([
            {"id": x["profile_id"], "name": x["name"], "group": gname.get(x["group_id"], ""),
             "last": last.get(x["profile_id"], ""), "sb": sb.get(x["profile_id"]),
             "next": min(nxt.get(x["profile_id"], [""])), "next_n": len(nxt.get(x["profile_id"], []))}
            for x in prof if group_ok(gname.get(x["group_id"], ""))])

    async def api_rewrite(req):
        body = await req.json()
        text = (body.get("text") or "").strip()
        if not text:
            raise web.HTTPBadRequest(text="text is empty")
        cands = await asyncio.to_thread(rewrite_text, text)
        return web.json_response({"text": cands[0], "candidates": cands})

    async def build_post(body):
        """投稿内容を検証して (profile_id, text, paths) を返す"""
        text = (body.get("text") or "").strip()
        profile_id = body.get("profile_id") or ""
        files = body.get("files") or []
        if not profile_id or not text:
            raise web.HTTPBadRequest(text="profile_id and text are required")
        prof = (await asyncio.to_thread(xdeck, "GET", "profile/list"))["data"]["list"]
        groups = (await asyncio.to_thread(xdeck, "GET", "group/list"))["data"]["list"]
        gname = {g["group_id"]: g["name"] for g in groups}
        target = next((x for x in prof if x["profile_id"] == profile_id), None)
        if not target or not group_ok(gname.get(target["group_id"], "")):
            raise web.HTTPBadRequest(text=f"このアカウントは{BOARD_NAME}ボードからは投稿できません")
        paths = []
        for f in files:
            orig = safe_path(f["id"], f["name"])
            ed = orig.parent / "_edited" / orig.name
            # 「加工版を使う」指定のときは、事前に加工して残してある版だけを使う(未加工のまま黙って投稿しない)
            if f.get("edited"):
                if not ed.is_file():
                    raise web.HTTPBadRequest(text=f"加工済みがありません: {orig.name}。先に「加工プレビュー」を実行してください")
                paths.append(str(ed))
            else:
                paths.append(str(orig))
        return profile_id, text, target["name"], paths

    async def api_post(req):
        body = await req.json()
        profile_id, text, _name, paths = await build_post(body)
        res = await send_post(body.get("work_id", ""), profile_id, text, paths)
        return web.json_response(res)

    # ---- 予約投稿 ----
    async def api_sched_add(req):
        body = await req.json()
        try:
            at = datetime.fromisoformat(str(body.get("at", "")))
        except ValueError:
            raise web.HTTPBadRequest(text="日時の形式が正しくありません")
        if at <= datetime.now():
            raise web.HTTPBadRequest(text="予約日時は現在より後にしてください")
        profile_id, text, pname, paths = await build_post(body)
        e = await add_sched(body.get("work_id", ""), profile_id, pname, text, paths, at)
        return web.json_response(e)

    async def api_imp_alert(req):
        b = await req.json()
        url = str(b.get("url", ""))
        if not re.match(r"^https://x\.com/[^/]+/status/\d+$", url):
            raise web.HTTPBadRequest(text="invalid url")
        ok = await asyncio.to_thread(register_imp_alert, url)
        return web.json_response({"ok": ok, "target": IMP_TARGET})

    async def api_sb_start(req):
        b = await req.json()
        ids = [str(x) for x in b.get("profile_ids", [])]
        valid = {p["id"] for p in await asyncio.to_thread(get_profiles) if group_ok(p["group"])}
        ids = [i for i in ids if i in valid]
        if not ids:
            raise web.HTTPBadRequest(text="対象のアカウントがありません")
        job = "sb-" + datetime.now().strftime("%H%M%S") + "-" + os.urandom(2).hex()
        SB_JOBS[job] = {"state": "running", "total": len(ids), "done": 0}
        asyncio.create_task(run_shadowban(job, ids))  # 1件ずつ順番に(Xdeck側の負荷を避ける)
        return web.json_response({"job": job})

    async def api_sb_status(req):
        st = SB_JOBS.get(req.match_info["job"])
        if not st:
            raise web.HTTPNotFound()
        return web.json_response(st)

    async def api_bulk(req):
        b = await req.json()
        try:
            start = max(datetime.fromisoformat(str(b["start"])), datetime.now() + timedelta(minutes=2))
            end = datetime.fromisoformat(str(b["end"]))
            per = int(b.get("per", 1))
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="入力が正しくありません")
        ids = [str(x) for x in b.get("profile_ids", [])]
        if not ids or not 1 <= per <= 20 or end <= start:
            raise web.HTTPBadRequest(text="アカウント・件数(1〜20)・時間帯(開始より後の終了)を確認してください")
        job = "bulk-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()
        BULK[job] = {"state": "running", "total": 0, "done": 0, "errors": [], "notes": []}
        asyncio.create_task(run_bulk(job, ids, start, end, per))
        return web.json_response({"job": job})

    async def api_bulk_status(req):
        st = BULK.get(req.match_info["job"])
        if not st:
            raise web.HTTPNotFound()
        return web.json_response(st)

    async def api_sched_list(_):
        return web.json_response(sorted(load_sched(), key=lambda x: x["at"]))

    async def api_sched_del(req):
        sid = req.match_info["sid"]
        async with SCHED_LOCK:
            items = load_sched()
            hit = next((x for x in items if x["id"] == sid), None)
            if not hit:
                raise web.HTTPNotFound()
            if hit["status"] == "running":
                raise web.HTTPConflict(text="投稿処理中のため取り消せません")
            save_sched([x for x in items if x["id"] != sid])
        shutil.rmtree(SAVE_DIR / "_sched" / sid, ignore_errors=True)
        return web.json_response({"ok": True})

    async def api_edit(req):
        b = await req.json()
        src = safe_path(b["id"], b["name"])
        dest = src.parent / "_edited" / src.name
        import random

        def rng(name: str, default_a: float, default_b: float, ndigits: int) -> float:
            x, y = float(b.get(name + "_a", default_a)), float(b.get(name + "_b", default_b))
            return round(random.uniform(min(x, y), max(x, y)), ndigits)

        lo = min(max(float(b.get("trim_min", 0.1)), 0.0), 2.0)
        hi = min(max(float(b.get("trim_max", 0.5)), lo), 2.0)
        head, tail = round(random.uniform(lo, hi), 2), round(random.uniform(lo, hi), 2)
        crop = rng("crop", 0.02, 0.02, 4)
        br, ct, sa = rng("br", 0.02, 0.08, 3), rng("ct", 1.05, 1.15, 3), rng("sa", 1.15, 1.15, 3)
        await asyncio.to_thread(edit_video, src, dest, crop, br, ct, sa, head, tail)
        return web.json_response({"url": f"/edited/{b['id']}/{src.name}?t={int(datetime.now().timestamp())}",
                                  "head": head, "tail": tail, "crop": crop, "brightness": br,
                                  "contrast": ct, "saturation": sa})

    async def edited_file(req):
        p = (SAVE_DIR / req.match_info["id"] / "_edited" / req.match_info["name"]).resolve()
        if SAVE_DIR.resolve() not in p.parents or not p.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    async def thumb(req):
        src = safe_path(req.match_info["id"], req.match_info["name"])
        if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            return web.FileResponse(src)
        t = src.parent / "_thumbs" / (src.stem + ".jpg")
        if not t.exists():
            await asyncio.to_thread(make_thumb, src, t)
        return web.FileResponse(t)

    async def api_history(req):
        wid = req.match_info["work"]
        out = []
        f = SAVE_DIR / "_posts.log"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if e.get("event") == "response" and e.get("work_id") == wid:
                    out.append({"at": e["at"], "profile_id": e["profile_id"], "text": e["text"],
                                "job_id": (e.get("response", {}).get("data") or {}).get("job_id")})
        return web.json_response(out[::-1])

    async def api_move(req):
        """保存済みの投稿を別の作品に移す。to が空なら新しい作品として分ける"""
        b = await req.json()
        d = SAVE_DIR / str(b.get("id", ""))
        mf = d / "meta.json"
        if "/" in str(b.get("id", "")) or not mf.is_file():
            raise web.HTTPNotFound()
        meta = json.loads(mf.read_text(encoding="utf-8"))
        meta["work_id"] = str(b.get("to") or "") or "split-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()
        mf.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return web.json_response({"work_id": meta["work_id"]})

    async def api_job(req):
        jid = req.match_info["job"]
        res = await asyncio.to_thread(xdeck, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})
        return web.json_response(res)

    app = web.Application()
    app.add_routes([
        web.get("/", index), web.get("/api/items", api_items),
        web.get("/files/{id}/{name}", files),
        web.post("/copy/{id}/{name}", copy_file),
        web.post("/copytext/{id}", copy_text),
        web.post("/copyurl/{id}/{url}", copy_url),
        web.get("/thumb/{id}/{name}", thumb), web.get("/api/history/{work}", api_history),
        web.post("/api/edit", api_edit), web.get("/edited/{id}/{name}", edited_file),
        web.get("/api/profiles", api_profiles), web.post("/api/rewrite", api_rewrite),
        web.post("/api/post", api_post), web.post("/api/bulk", api_bulk), web.post("/api/shadowban", api_sb_start), web.get("/api/shadowban/{job}", api_sb_status), web.post("/api/imp_alert", api_imp_alert), web.get("/api/bulk/{job}", api_bulk_status), web.post("/api/move", api_move), web.get("/api/schedule", api_sched_list),
        web.post("/api/schedule", api_sched_add), web.delete("/api/schedule/{sid}", api_sched_del), web.get("/api/job/{job}", api_job),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    # コピー系は操作を伴うので自分のMacからのみ受け付ける
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    print(f"gallery: {GALLERY_URL}")


intents = discord.Intents.default()
intents.message_content = True


class Bot(discord.Client):
    async def setup_hook(self):
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        await start_web()
        self.sched_task = asyncio.create_task(scheduler_loop())


client = Bot(intents=intents)


@client.event
async def on_ready():
    print(f"logged in as {client.user} / save dir: {SAVE_DIR}")


@client.event
async def on_message(msg: discord.Message):
    import asyncio

    if msg.author.bot:
        return
    in_thread = isinstance(msg.channel, discord.Thread)
    channel_id = msg.channel.parent_id if in_thread else msg.channel.id
    if CHANNEL_IDS and channel_id not in CHANNEL_IDS:
        return
    if not ENT and channel_id in ENT_CHANNELS:
        return
    m = URL_RE.search(msg.content)
    work_urls = [] if ENT else find_work_urls(msg.content)  # エンタメ用は作品URLなし
    # スレッド外の MyFans/FANZA だけの投稿は、紐づけ先の作品がないので無視
    if not m and not (work_urls and in_thread):
        return
    # 作品ID: スレッド内なら そのスレッドID。スレッド外なら このメッセージID。
    # (メッセージから作ったスレッドのIDは元メッセージIDと同じなので、最初の投稿と後続が同じ作品になる)
    work_id = str(msg.channel.id if in_thread else msg.id)
    try:
        notes = []
        if work_urls:
            new = await asyncio.to_thread(add_work_urls, work_id, work_urls)
            if new:
                notes.append("作品URLを登録: " + ", ".join(x["site"] for x in new))
        tw = None
        if m:
            if await asyncio.to_thread(already_saved, work_id, m.group(2)):
                notes.append("X投稿は保存済み")
            else:
                folder, videos, tw = await asyncio.to_thread(
                    save_tweet, m.group(1), m.group(2), work_id,
                    {"url": msg.jump_url, "thread": msg.channel.name if in_thread else None})
                notes.append("X投稿を保存")
        await msg.add_reaction("✅" if (tw or work_urls) else "♻️")
        summary = " / ".join(notes) or "変更なし"

        if in_thread:
            await msg.reply(f"{summary}\n{GALLERY_URL}", mention_author=False)
            return
        # 最初のリンク: スレッドを作り、以降のリンクをここに送ればこの作品にまとまる
        title = ((tw or {}).get("text") or m.group(1)).replace("\n", " ")[:50]
        try:
            thread = await msg.create_thread(name=title or "作品")
            await thread.send(f"{summary}\n{GALLERY_URL}\n同じ作品のXリンク・MyFans/FANZAのURLはこのスレッドに送ってください")
        except discord.Forbidden:
            await msg.reply(f"{summary}\n{GALLERY_URL}\n(スレッド作成の権限がないため、続きの追加はできません)",
                            mention_author=False)
    except Exception as e:  # noqa: BLE001
        await msg.add_reaction("❌")
        await msg.reply(f"保存失敗: {e}", mention_author=False)


client.run(TOKEN)
