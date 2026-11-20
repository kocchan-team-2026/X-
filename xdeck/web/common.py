"""Web層の共通部品。"""
from pathlib import Path

from aiohttp import web

from ..config import POSTS_DIR


def safe_path(item_id: str, name: str) -> Path:
    """posts/<item_id>/<name> を、posts/ の外に出ないことを確認して返す(なければ404)"""
    p = (POSTS_DIR / item_id / name).resolve()
    if POSTS_DIR.resolve() not in p.parents or not p.is_file():
        raise web.HTTPNotFound()
    return p
