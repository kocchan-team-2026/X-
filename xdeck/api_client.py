"""Xdeck ローカル API のクライアント。"""
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
