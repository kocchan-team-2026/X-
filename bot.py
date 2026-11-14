"""Discord に投げた X(Twitter) のリンクを検知し、本文・画像・動画をローカル保存する Bot。
動画は保存後に macOS のクリップボードへファイルとしてコピーする (Cmd+V で貼り付け可能)。
"""
import json
import os
import re
import subprocess
from datetime import datetime
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
SAVE_DIR = Path(os.environ.get("SAVE_DIR", Path(__file__).parent / "saved"))
# 空なら全チャンネル。カンマ区切りでチャンネルIDを指定すると限定できる
CHANNEL_IDS = {int(x) for x in os.environ.get("CHANNEL_IDS", "").split(",") if x.strip()}

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
    """Claude Code (claude -p) で本文を強めにリライトし、書き方の違う3案を返す。URLは書き換えず元のまま付け直す。"""
    import random
    found = re.findall(r"https?://\S+", text)
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
    # 元のURLを、そのまま末尾に戻す
    return [c + ("\n" + "\n".join(found) if found else "") for c in cands]


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


def save_tweet(user: str, tweet_id: str, work_id: str) -> tuple[Path, list[Path], dict]:
    res = requests.get(f"https://api.fxtwitter.com/{user}/status/{tweet_id}", timeout=30)
    res.raise_for_status()
    tw = res.json()["tweet"]

    folder = SAVE_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tw['author']['screen_name']}_{tweet_id}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "meta.json").write_text(json.dumps({
        "work_id": work_id, "tweet_id": tweet_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
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


PORT = int(os.environ.get("GALLERY_PORT", "8765"))
GALLERY_URL = f"http://localhost:{PORT}"

def page() -> str:
    return (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")


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
        return web.json_response([
            {"id": x["profile_id"], "name": x["name"], "group": gname.get(x["group_id"], "")} for x in prof])

    async def api_rewrite(req):
        body = await req.json()
        text = (body.get("text") or "").strip()
        if not text:
            raise web.HTTPBadRequest(text="text is empty")
        cands = await asyncio.to_thread(rewrite_text, text)
        return web.json_response({"text": cands[0], "candidates": cands})

    async def api_post(req):
        body = await req.json()
        text = (body.get("text") or "").strip()
        profile_id = body.get("profile_id") or ""
        files = body.get("files") or []
        if not profile_id or not text:
            raise web.HTTPBadRequest(text="profile_id and text are required")
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
        payload = {"kind": "post", "profile_ids": [profile_id], "text": text}
        if paths:
            payload["media_paths"] = paths
        log = {"at": datetime.now().isoformat(timespec="seconds"), "work_id": body.get("work_id", ""), "profile_id": profile_id,
               "text": text, "media": paths}

        def write_log(extra):
            with open(SAVE_DIR / "_posts.log", "a", encoding="utf-8") as lf:
                lf.write(json.dumps({**log, **extra}, ensure_ascii=False) + "\n")

        write_log({"event": "request"})  # 先に記録(失敗しても何を送ったか残る)
        # Xdeck は投稿完了まで応答を返さないことがある(30秒前後)ので長めに待つ
        res = await asyncio.to_thread(xdeck, "POST", "x/bulk", json=payload, timeout=300)
        write_log({"event": "response", "response": res})
        return web.json_response(res)

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
        web.post("/api/post", api_post), web.get("/api/job/{job}", api_job),
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
    m = URL_RE.search(msg.content)
    work_urls = find_work_urls(msg.content)
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
                folder, videos, tw = await asyncio.to_thread(save_tweet, m.group(1), m.group(2), work_id)
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
