"""シャドウバン判定(Xdeck の x/shadowban)。"""
import asyncio
import json
from datetime import datetime

from ..api_client import api
from ..config import STATE_DIR
from ..storage import write_json_atomic


SB_FILE = lambda: STATE_DIR / "_shadowban.json"  # noqa: E731
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
                info = (await asyncio.to_thread(api, "GET", "x/get", params={"profile_id": pid}))["data"]["profile"]
                res = await asyncio.to_thread(api, "GET", "x/shadowban", params={"screen_name": info["screenName"]}, timeout=180)
                if res.get("code") != 0:
                    raise RuntimeError(res.get("msg") or "failed")
                summ = sb_summary(res["data"])
            except Exception as e:  # noqa: BLE001
                summ = {"level": "unknown", "label": "判定不能", "verdict": None, "flags": [], "score": None,
                        "error": str(e)[:120], "checked_at": datetime.now().isoformat(timespec="seconds")}
            async with SB_LOCK:
                d = sb_load()
                d[pid] = summ
                write_json_atomic(SB_FILE(), d, indent=1)
            st["done"] += 1
        st["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        st["state"] = "error"
        st["error"] = str(e)[:200]
