"""定常予約(毎日決まった時間帯の自動一括予約)の設定・日別の変更のルート。"""
import asyncio
from datetime import datetime, timedelta

from aiohttp import web

from ..services import routine as R

routes = web.RouteTableDef()
DAYS = 7


def _time_pair(start: str, end: str) -> None:
    if not R.valid_time(start) or not R.valid_time(end) or start == "24:00":
        raise web.HTTPBadRequest(text="時刻は 00:00〜23:59(終了は 24:00 まで)で指定してください")
    day = "2000-01-01"
    if R.hm_dt(day, end) <= R.hm_dt(day, start):
        raise web.HTTPBadRequest(text="終了は開始より後にしてください")


def _check_day(day: str) -> None:
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise web.HTTPBadRequest(text="日付の形式が正しくありません")
    if d < datetime.now().date():
        raise web.HTTPBadRequest(text="過去の日付は変更できません")


def _slot(cfg: dict, sid: str) -> dict:
    s = next((x for x in cfg["slots"] if x["id"] == sid), None)
    if not s:
        raise web.HTTPBadRequest(text="時間帯が見つかりません")
    return s


@routes.get("/api/routine")
async def api_routine(_):
    cfg = R.load()
    now = datetime.now()
    days = []
    for i in range(DAYS):
        d = (now + timedelta(days=i)).date()
        day = d.strftime("%Y-%m-%d")
        slots = []
        for s in cfg["slots"]:
            st, en, skip, changed = R.window(cfg, day, s)
            run = cfg["runs"].get(R.run_key(day, s["id"]))
            if skip:
                state = "skip"
            elif run:
                state = run["state"]
            elif not s.get("enabled", True):
                state = "off"
            elif now >= R.hm_dt(day, en):
                state = "late"
            else:
                state = "plan"
            slots.append({"id": s["id"], "start": st, "end": en, "skip": skip, "changed": changed, "state": state,
                          "run": run})
        days.append({"date": day, "wd": "月火水木金土日"[d.weekday()], "slots": slots})
    return web.json_response({"enabled": cfg["enabled"], "lead_min": R.LEAD_MIN, "slots": cfg["slots"], "days": days})


@routes.put("/api/routine/config")
async def api_routine_config(req):
    b = await req.json()
    async with R.ROUTINE_LOCK:
        cfg = R.load()
        if "enabled" in b:
            cfg["enabled"] = bool(b["enabled"])
        for x in b.get("slots", []):
            s = _slot(cfg, str(x.get("id")))
            st, en = str(x.get("start", s["start"])), str(x.get("end", s["end"]))
            _time_pair(st, en)
            s.update(start=st, end=en, enabled=bool(x.get("enabled", s.get("enabled", True))))
            if s["mode"] == "imp_below":
                try:
                    s["imp_max"] = max(0, int(x.get("imp_max", s.get("imp_max", 1000))))
                except (TypeError, ValueError):
                    raise web.HTTPBadRequest(text="impは数字で指定してください")
        R.save(cfg)
    if cfg["enabled"]:
        asyncio.create_task(R.run_routine())
    return web.json_response({"ok": True})


@routes.put("/api/routine/day")
async def api_routine_day(req):
    """その日だけの変更。start/end=時間帯を変える / skip=その日は休む / clear=基本設定に戻す。
    すでに予約を作ったあとなら、待機中の予約を取り消して作り直す"""
    b = await req.json()
    day, sid = str(b.get("date", "")), str(b.get("slot", ""))
    _check_day(day)
    async with R.ROUTINE_LOCK:
        cfg = R.load()
        s = _slot(cfg, sid)
        ov = cfg["overrides"].setdefault(day, {})
        if b.get("clear"):
            ov.pop(sid, None)
        else:
            cur = ov.get(sid, {})
            st, en = str(b.get("start", cur.get("start", s["start"]))), str(b.get("end", cur.get("end", s["end"])))
            _time_pair(st, en)
            ov[sid] = {"start": st, "end": en, "skip": bool(b.get("skip", False))}
        R.save(cfg)
    n = 0
    if (cfg["runs"].get(R.run_key(day, sid)) or {}).get("state") in ("done", "error"):
        try:
            n = await R.reset_slot(day, sid)
        except RuntimeError as e:
            raise web.HTTPConflict(text=str(e))
    if cfg["enabled"]:
        asyncio.create_task(R.run_routine())
    return web.json_response({"ok": True, "cancelled": n})


@routes.post("/api/routine/rebuild")
async def api_routine_rebuild(req):
    """予約を作り直す(待機中の予約を取り消して、もう一度作る)"""
    b = await req.json()
    day, sid = str(b.get("date", "")), str(b.get("slot", ""))
    _check_day(day)
    try:
        n = await R.reset_slot(day, sid)
    except RuntimeError as e:
        raise web.HTTPConflict(text=str(e))
    if R.load()["enabled"]:
        asyncio.create_task(R.run_routine())
    return web.json_response({"ok": True, "cancelled": n})
