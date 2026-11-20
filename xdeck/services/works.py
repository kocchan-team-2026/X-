"""作品(Discordスレッド単位)と、保存した投稿の管理。"""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..config import ANY_URL_RE, POSTS_DIR, WORK_SITES, WORKS_DIR
from ..media import download


def find_work_urls(text: str) -> list[dict]:
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


def already_saved(work_id: str, tweet_id: str) -> bool:
    for meta in POSTS_DIR.glob("*/meta.json"):
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

    folder = POSTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tw['author']['screen_name']}_{tweet_id}"
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


def list_items():
    """保存済みの投稿を、Discord スレッド(作品)ごとにまとめて返す。新しい作品が先頭。"""
    works: dict[str, dict] = {}
    for d in sorted((p for p in POSTS_DIR.glob("*") if p.is_dir())):
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
        try:
            meta_w = json.loads(f.read_text(encoding="utf-8"))
            w["affiliate"] = meta_w.get("affiliate", "")
            w["weight"] = meta_w.get("weight", 1)
        except Exception:  # noqa: BLE001
            pass
        w["latest"] = max(w["latest"], datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y%m%d_%H%M%S"))
    for w in works.values():
        w.setdefault("urls", [])
        w.setdefault("affiliate", "")
        w.setdefault("weight", 1)
        times = [p["saved_at"] for p in w["posts"]] + [u.get("added_at", "") for u in w["urls"]]
        times = [t for t in times if t]
        w["created_at"], w["updated_at"] = (min(times), max(times)) if times else ("", "")
    return sorted(works.values(), key=lambda w: w["updated_at"] or w["latest"], reverse=True)


def work_affiliate(wid: str) -> str:
    f = WORKS_DIR / f"{wid}.json"
    if not wid or "/" in wid or not f.exists():
        return ""
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("affiliate", "") or ""
    except Exception:  # noqa: BLE001
        return ""
