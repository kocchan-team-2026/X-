"""Xdeck ローカル API のクライアント。"""
import asyncio

import requests

from .config import IMP_TARGET, XDECK_TOKEN, XDECK_URL


def api(method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{XDECK_URL}/{path}", headers={"X-Api-Token": XDECK_TOKEN},
                         timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r.json()


def get_profiles() -> list[dict]:
    prof = api("GET", "profile/list")["data"]["list"]
    gname = {g["group_id"]: g["name"] for g in api("GET", "group/list")["data"]["list"]}
    return [{"id": x["profile_id"], "name": x["name"], "group": gname.get(x["group_id"], "")} for x in prof]


def register_imp_alert(url: str) -> bool:
    """投稿を Xdeck のインプ達成通知に登録する(失敗しても投稿には影響させない)"""
    try:
        r = api("POST", "imp-alerts/create", json={
            "tweet": url, "url": url, "target": IMP_TARGET, "target_views": IMP_TARGET, "targetViews": IMP_TARGET})
        return r.get("code") == 0
    except Exception as e:  # noqa: BLE001
        print("imp alert error:", e)
        return False


class JobTimeout(RuntimeError):
    """Xdeck のジョブが待ち時間内に終わらなかった(投稿できたかは不明)"""


async def wait_job(jid, tries: int = 60) -> dict:
    """Xdeck の投稿ジョブが終わるまで2秒おきに確認し、最終状態を返す。終わらなければ JobTimeout"""
    for _ in range(tries):
        job = ((await asyncio.to_thread(api, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})).get("data")) or {}
        if str(job.get("state")).lower() in ("done", "failed", "error", "finished", "completed"):
            return job
        await asyncio.sleep(2)
    raise JobTimeout(f"Xdeck の処理が{tries * 2}秒以内に終わりませんでした。投稿されたかどうかは X で確認してください")


def job_error(job: dict, default: str = "Xdeck 側で投稿に失敗しました") -> str:
    """Xdeck のジョブの失敗理由。job["error"] は空のことが多く、本当の理由は steps[].error に入っている"""
    msgs = [str(s["error"]).strip() for s in (job.get("steps") or []) if s.get("error")]
    return (job.get("error") or " / ".join(dict.fromkeys(msgs)) or default)[:300]


def stop_browser(profile_id: str) -> bool:
    """アカウントのブラウザ(Xdeck 上の)を止める。次にそのアカウントで操作すると、Xdeck が自動で起動し直す。
    通信が通らなくなったアカウントは、これで復活することが多い。失敗しても例外は出さない"""
    try:
        return api("GET", "browser/stop", params={"profile_id": profile_id}, timeout=30).get("code") == 0
    except Exception as e:  # noqa: BLE001
        print("browser stop error:", str(e)[:100])
        return False
