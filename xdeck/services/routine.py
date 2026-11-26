"""定常予約: 毎日決まった時間帯に、全アカウント(またはimpが低いアカウント)の投稿を自動で一括予約する。

設定は state/_routine.json。基本の時間帯(slots)と、日付ごとの変更(overrides: 時間を変える/その日は休む)、
実行の記録(runs)を持つ。各時間帯は、開始の LEAD_MIN 分前(imp条件つきは開始ちょうど)に、
一括予約と同じ仕組みで「その時間帯の中のランダムな時刻」に予約を作る。
"""
import asyncio
import json
import re
import shutil
from datetime import datetime, timedelta

from ..api_client import api, get_profiles
from ..config import ENT, FORTUNE, STATE_DIR, group_ok
from ..storage import load_sched, save_sched, write_json_atomic
from .bulk import BULK, run_bulk
from .imps import last_tweets
from .scheduler import SCHED_LOCK


LEAD_MIN = 60  # 時間帯の開始のこれだけ前に予約を作る(画面で確認・取り消しできるように)
KEEP_DAYS = 30
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$")
ROUTINE_LOCK = asyncio.Lock()

# mode: all=全アカウント / imp_below=その日の前の投稿のimpが imp_max 以下のアカウントだけ
DEFAULT_SLOTS = [] if FORTUNE else ([
    {"id": "am", "label": "朝", "start": "06:00", "end": "10:00", "mode": "all", "enabled": True},
    {"id": "pm", "label": "午後", "start": "14:00", "end": "17:00", "mode": "all", "enabled": True},
    {"id": "night", "label": "夜", "start": "22:00", "end": "24:00", "mode": "all", "enabled": True},
] if ENT else [
    {"id": "am", "label": "朝", "start": "12:00", "end": "15:00", "mode": "all", "enabled": True},
    {"id": "pm", "label": "夜", "start": "17:00", "end": "20:00", "mode": "imp_below", "imp_max": 1000, "enabled": True},
])


def _file():
    return STATE_DIR / "_routine.json"


def load() -> dict:
    f = _file()
    d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    saved = {s["id"]: s for s in d.get("slots", [])}
    slots = []
    for base in DEFAULT_SLOTS:  # 時間帯の種類(id・条件)はコード側で固定。時間・ON/OFF・しきい値だけ保存値を使う
        s = {**base, **{k: saved[base["id"]][k] for k in ("start", "end", "enabled", "imp_max")
                        if base["id"] in saved and k in saved[base["id"]]}}
        slots.append(s)
    return {"enabled": bool(d.get("enabled", False)), "slots": slots,
            "overrides": d.get("overrides", {}), "runs": d.get("runs", {})}


def save(cfg: dict) -> None:
    cut = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    cfg["runs"] = {k: v for k, v in cfg["runs"].items() if k[:10] >= cut}
    cfg["overrides"] = {k: v for k, v in cfg["overrides"].items() if k >= cut and v}
    write_json_atomic(_file(), cfg)


def valid_time(t: str) -> bool:
    return bool(TIME_RE.match(str(t)))


def hm_dt(day: str, t: str) -> datetime:
    """'2026-11-22' と '24:00' → その日の終わり(翌日 0:00)"""
    d = datetime.fromisoformat(day)
    if t == "24:00":
        return d + timedelta(days=1)
    h, m = t.split(":")
    return d.replace(hour=int(h), minute=int(m))


def window(cfg: dict, day: str, slot: dict) -> tuple[str, str, bool, bool]:
    """(開始, 終了, この日はスキップ, この日だけ変更あり)"""
    ov = (cfg["overrides"].get(day) or {}).get(slot["id"]) or {}
    return ov.get("start", slot["start"]), ov.get("end", slot["end"]), bool(ov.get("skip")), bool(ov)


def run_key(day: str, sid: str) -> str:
    return f"{day}:{sid}"


async def morning_imps(day: str, start: datetime, pids: list[str]) -> dict[str, int | None]:
    """各アカウントの「この日、時間帯の開始より前に投稿した最新の投稿」のインプ数。投稿がなければ値なし(キーなし)"""
    day0 = f"{day}T00:00"
    lim = start.isoformat(timespec="seconds")
    last = last_tweets()
    targets = {p: t for p, t in last.items() if p in pids and day0 <= t["at"] < lim}
    sem = asyncio.Semaphore(4)
    views: dict[str, int | None] = {}

    async def one(pid: str, t: dict) -> None:
        async with sem:
            try:
                r = await asyncio.to_thread(api, "GET", "x/tweet", params={"profile_id": pid, "tweet": t["tweet_id"]}, timeout=90)
                v = ((r.get("data") or {}).get("counts") or {}).get("views")
                views[pid] = int(v) if v is not None else None
            except Exception:  # noqa: BLE001
                views[pid] = None

    await asyncio.gather(*(one(p, t) for p, t in targets.items()))
    return views


async def generate(cfg_slot: dict, day: str, start_s: str, end_s: str) -> dict:
    """1つの時間帯の予約を作って、実行記録(dict)を返す"""
    now = datetime.now()
    start = max(hm_dt(day, start_s), now + timedelta(minutes=2))
    end = hm_dt(day, end_s)
    notes: list[str] = []
    profs = await asyncio.to_thread(get_profiles)
    ids = [p["id"] for p in profs if group_ok(p["group"])]
    if cfg_slot["mode"] == "imp_below":
        limit = int(cfg_slot.get("imp_max", 1000))
        views = await morning_imps(day, hm_dt(day, start_s), ids)
        keep, over, unk, none = [], 0, 0, 0
        for i in ids:
            if i not in views:
                keep.append(i)  # この日はまだ投稿していない → 対象にする
                none += 1
            elif views[i] is None:
                unk += 1  # インプが取れなかったアカウントは見送る
            elif views[i] <= limit:
                keep.append(i)
            else:
                over += 1
        notes.append(f"{limit}impを超えていて除外: {over}件 / imp取得失敗で除外: {unk}件 / 前の投稿なしで対象: {none}件")
        ids = keep
    rec = {"state": "done", "at": now.isoformat(timespec="seconds"), "candidates": len(ids), "notes": notes}
    if not ids:
        rec.update(total=0, reserved=0, errors=[])
        return rec
    job = "routine-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + cfg_slot["id"]
    BULK[job] = {"state": "running", "total": 0, "done": 0, "errors": [], "notes": []}
    await run_bulk(job, ids, start, end, 1, {"routine": run_key(day, cfg_slot["id"])})
    st = BULK.pop(job, {})
    errs = st.get("errors", [])
    rec.update(total=st.get("total", 0), reserved=max(st.get("total", 0) - len(errs), 0), errors=errs[:20],
               notes=notes + st.get("notes", [])[:20], job=job)
    if st.get("state") == "error":
        rec["state"] = "error"
    return rec


async def run_routine() -> None:
    async with ROUTINE_LOCK:
        cfg = load()
        if not cfg["enabled"]:
            return
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        for slot in cfg["slots"]:
            key = run_key(day, slot["id"])
            if not slot.get("enabled", True) or key in cfg["runs"]:
                continue
            s, e, skip, _ = window(cfg, day, slot)
            if skip or now >= hm_dt(day, e):
                continue
            gen_at = hm_dt(day, s) - timedelta(minutes=0 if slot["mode"] == "imp_below" else LEAD_MIN)
            if now < gen_at:
                continue
            cfg["runs"][key] = {"state": "running", "at": now.isoformat(timespec="seconds")}
            save(cfg)
            try:
                rec = await generate(slot, day, s, e)
            except Exception as ex:  # noqa: BLE001
                rec = {"state": "error", "at": now.isoformat(timespec="seconds"), "errors": [str(ex)[:200]],
                       "notes": [], "total": 0, "reserved": 0}
            cfg = load()  # 実行中に設定が変わっていても、その変更を消さない
            cfg["runs"][key] = rec
            save(cfg)
            print(f"routine: {key} {rec['state']} 予約{rec.get('reserved', 0)}件")


async def reset_slot(day: str, sid: str) -> int:
    """その日・その時間帯で作った予約のうち待機中のものを取り消し、実行記録を消す(次の確認で作り直される)"""
    key = run_key(day, sid)
    async with ROUTINE_LOCK:
        cfg = load()
        if (cfg["runs"].get(key) or {}).get("state") == "running":
            raise RuntimeError("予約の作成中です。少し待ってからやり直してください")
        n = 0
        async with SCHED_LOCK:
            items = load_sched()
            keep = []
            for x in items:
                if x.get("routine") == key and x["status"] == "pending":
                    shutil.rmtree(STATE_DIR / "_sched" / x["id"], ignore_errors=True)
                    n += 1
                else:
                    keep.append(x)
            if n:
                save_sched(keep)
        cfg["runs"].pop(key, None)
        save(cfg)
        return n


async def routine_loop() -> None:
    # 前回の終了で「作成中」のまま残った記録は、中断扱いにする
    try:
        cfg = load()
        for k, v in cfg["runs"].items():
            if v.get("state") == "running":
                cfg["runs"][k] = {**v, "state": "error", "errors": ["中断されました。「作り直す」で再実行できます"]}
        save(cfg)
    except Exception as e:  # noqa: BLE001
        print("routine recover error:", e)
    while True:
        try:
            await run_routine()
        except Exception as e:  # noqa: BLE001
            print("routine error:", e)
        await asyncio.sleep(60)
