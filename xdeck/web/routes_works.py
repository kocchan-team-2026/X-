"""作品・保存した投稿・動画加工まわりのルート。"""
import asyncio
import json

import re
import shutil
import subprocess
from datetime import datetime
import os

from aiohttp import web

from .. import platform_utils
from ..config import ENT, FORTUNE, POSTS_DIR, STATE_DIR, WORKS_DIR
from ..media import copy_file_to_clipboard, edit_video, make_thumb
from ..rewrite import rewrite_text
from ..services.works import list_items
from ..storage import read_posts_log, write_json_atomic
from .common import safe_path

routes = web.RouteTableDef()


@routes.get("/api/items")
async def api_items(_):
    return web.json_response(list_items())


@routes.get("/files/{id}/{name}")
async def files(req):
    return web.FileResponse(safe_path(req.match_info["id"], req.match_info["name"]))


@routes.post("/copy/{id}/{name}")
async def copy_file(req):
    p = safe_path(req.match_info["id"], req.match_info["name"])
    await asyncio.to_thread(copy_file_to_clipboard, p)
    return web.Response(text="ok")


@routes.post("/copytext/{id}")
async def copy_text(req):
    p = safe_path(req.match_info["id"], "tweet.json")
    text = json.loads(p.read_text(encoding="utf-8"))["text"]
    await asyncio.to_thread(platform_utils.copy_text, text)
    return web.Response(text="ok")


@routes.post("/copyurl/{id}/{url}")
async def copy_url(req):
    # 保存済みの作品URLだけコピー可 (任意文字列は受け付けない)
    wid, url = req.match_info["id"], req.match_info["url"]
    f = WORKS_DIR / f"{wid}.json"
    if "/" in wid or not f.exists() or url not in {x["url"] for x in json.loads(f.read_text(encoding="utf-8"))["urls"]}:
        raise web.HTTPNotFound()
    await asyncio.to_thread(platform_utils.copy_text, url)
    return web.Response(text="ok")


@routes.get("/thumb/{id}/{name}")
async def thumb(req):
    src = safe_path(req.match_info["id"], req.match_info["name"])
    if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return web.FileResponse(src)
    t = src.parent / "_thumbs" / (src.stem + ".jpg")
    if not t.exists():
        await asyncio.to_thread(make_thumb, src, t)
    return web.FileResponse(t)


@routes.post("/api/edit")
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


@routes.get("/edited/{id}/{name}")
async def edited_file(req):
    p = (POSTS_DIR / req.match_info["id"] / "_edited" / req.match_info["name"]).resolve()
    if POSTS_DIR.resolve() not in p.parents or not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p)


@routes.post("/api/rewrite")
async def api_rewrite(req):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="text is empty")
    cands = await asyncio.to_thread(rewrite_text, text)
    return web.json_response({"text": cands[0], "candidates": cands})


@routes.get("/api/history/{work}")
async def api_history(req):
    wid = req.match_info["work"]
    out = []
    for e in read_posts_log():
        if e.get("event") == "response" and e.get("work_id") == wid:
            out.append({"at": e["at"], "profile_id": e["profile_id"], "text": e["text"],
                        "job_id": (e.get("response", {}).get("data") or {}).get("job_id")})
    return web.json_response(out[::-1])


@routes.post("/api/move")
async def api_move(req):
    """保存済みの投稿を別の作品に移す。to が空なら新しい作品として分ける"""
    b = await req.json()
    d = POSTS_DIR / str(b.get("id", ""))
    mf = d / "meta.json"
    if "/" in str(b.get("id", "")) or not mf.is_file():
        raise web.HTTPNotFound()
    meta = json.loads(mf.read_text(encoding="utf-8"))
    meta["work_id"] = str(b.get("to") or "") or "split-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()
    mf.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"work_id": meta["work_id"]})


@routes.post("/api/delete_work")
async def api_delete_work(req):
    """作品を削除。完全には消さず、state/_trash/ に移す(戻せるように)"""
    b = await req.json()
    wid = str(b.get("work_id", ""))
    if not wid or "/" in wid or wid.startswith(".") or wid.startswith("_"):
        raise web.HTTPBadRequest(text="invalid work_id")
    mine = []
    for d in POSTS_DIR.glob("*"):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
        if (meta.get("work_id") or d.name) == wid:
            mine.append(d)
    wf = WORKS_DIR / f"{wid}.json"
    if not mine and not wf.exists():
        raise web.HTTPNotFound()
    dest = STATE_DIR / "_trash" / f"{datetime.now():%Y%m%d_%H%M%S}_{wid}"
    dest.mkdir(parents=True, exist_ok=True)
    for d in mine:
        shutil.move(str(d), str(dest / d.name))
    if wf.exists():
        shutil.move(str(wf), str(dest / "_work.json"))
    return web.json_response({"ok": True, "moved": len(mine)})


def update_work(wid: str, **fields) -> None:
    """作品の設定(state/_works/<作品ID>.json)の項目を更新する。作品がなければ404"""
    exists = any(
        json.loads(m.read_text(encoding="utf-8")).get("work_id") == wid for m in POSTS_DIR.glob("*/meta.json"))
    f = WORKS_DIR / f"{wid}.json"
    if not exists and not f.exists():
        raise web.HTTPNotFound()
    WORKS_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"urls": []}
    data.update(fields)
    write_json_atomic(f, data)


@routes.post("/api/affiliate")
async def api_affiliate(req):
    """作品のアフィリエイトリンク(MyFansで手動作成したURL)を保存。空文字で消去"""
    if ENT:
        raise web.HTTPNotFound()
    b = await req.json()
    wid = str(b.get("work_id", ""))
    url = str(b.get("url", "")).strip()
    if not wid or "/" in wid or wid.startswith("."):
        raise web.HTTPBadRequest(text="invalid work_id")
    if url and (not re.match(r"^https?://\S+$", url) or len(url) > 2000):
        raise web.HTTPBadRequest(text="http(s)://から始まるURLを入れてください")
    update_work(wid, affiliate=url, affiliate_at=datetime.now().isoformat(timespec="seconds") if url else "")
    return web.json_response({"affiliate": url})


@routes.post("/api/weight")
async def api_weight(req):
    """作品の「選ばれやすさ」(一括予約のランダム選択の重み)を保存。0〜10、標準1"""
    if ENT:
        raise web.HTTPNotFound()
    b = await req.json()
    wid = str(b.get("work_id", ""))
    try:
        wt = round(float(b.get("weight")), 2)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="数値を入れてください")
    if not wid or "/" in wid or wid.startswith(".") or not 0 <= wt <= 10:
        raise web.HTTPBadRequest(text="0〜10の数値を入れてください")
    update_work(wid, weight=wt)
    return web.json_response({"weight": wt})


@routes.post("/api/fortune/plan")
async def api_fortune_plan(req):
    """占い用: 投稿の予定日時(planned_at)と、1つ目のリプの本文(followup_text)を保存する。どちらか片方だけでもよい"""
    if not FORTUNE:
        raise web.HTTPNotFound()
    b = await req.json()
    wid = str(b.get("work_id", ""))
    if not wid or "/" in wid or wid.startswith("."):
        raise web.HTTPBadRequest(text="invalid work_id")
    fields = {}
    if "planned_at" in b:
        try:
            fields["planned_at"] = datetime.fromisoformat(str(b["planned_at"])).isoformat(timespec="minutes")
        except ValueError:
            raise web.HTTPBadRequest(text="日時の形式が正しくありません")
    if "followup_text" in b:
        text = str(b["followup_text"]).strip()
        if len(text) > 270:
            raise web.HTTPBadRequest(text="リプは270文字以内にしてください")
        fields["followup_text"] = text
    update_work(wid, **fields)
    return web.json_response(fields)


@routes.post("/api/fortune/schedule_all")
async def api_fortune_schedule_all(req):
    """占い用の一括予約: 「準備完了」の投稿案を、それぞれに設定した日時(planned_at)で予約する。
    準備完了 = 本文がある・日時が未来・リプの文とリンクが入っている・まだ予約していない。dry=true なら、予約せず内容だけ返す"""
    if not FORTUNE:
        raise web.HTTPNotFound()
    from ..api_client import api
    from ..config import group_ok
    from ..services.scheduler import add_sched
    b = await req.json() if req.can_read_body else {}
    prof = (await asyncio.to_thread(api, "GET", "profile/list"))["data"]["list"]
    groups = (await asyncio.to_thread(api, "GET", "group/list"))["data"]["list"]
    gname = {g["group_id"]: g["name"] for g in groups}
    cands = [p for p in prof if group_ok(gname.get(p["group_id"], ""))]
    if b.get("profile_id"):
        cands = [p for p in cands if p["profile_id"] == b["profile_id"]]
    if len(cands) != 1:
        raise web.HTTPBadRequest(text="占いのアカウントを1つに決められません(占いグループのアカウントを確認してください)")
    target = cands[0]
    now = datetime.now()
    items, made = [], 0
    for w in sorted(list_items(), key=lambda x: x.get("planned_at") or "9"):
        text = (w["posts"][0]["text"] if w.get("posts") else "").strip()
        at = w.get("planned_at") or ""
        row = {"work_id": w["work_id"], "at": at, "text": text[:40], "ok": False, "reason": ""}
        st = (w.get("sched") or {}).get("status")
        if not text:
            row["reason"] = "本文がありません"
        elif not at:
            row["reason"] = "投稿の日時が未設定です"
        elif datetime.fromisoformat(at) <= now:
            row["reason"] = "日時が過ぎています"
        elif st in ("pending", "running", "done"):
            row["reason"] = "予約済み"
        elif not (w.get("followup_text") or "").strip() or not (w.get("affiliate") or "").strip():
            row["reason"] = "リプの文かリンクが未設定です"
        else:
            row["ok"] = True
            if not b.get("dry"):
                await add_sched(w["work_id"], target["profile_id"], target["name"], text, [], datetime.fromisoformat(at))
                made += 1
        items.append(row)
    return web.json_response({"profile": target["name"], "items": items, "made": made})
