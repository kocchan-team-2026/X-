"""state/ に置く管理データ(予約・投稿履歴)の読み書き。"""
import json
from pathlib import Path

from .config import STATE_DIR


def write_json_atomic(path: Path, data, indent: int | None = 2) -> None:
    """途中で止まっても壊れないよう、一時ファイルに書いてから置き換える"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def sched_file() -> Path:
    return STATE_DIR / "_schedule.json"


def load_sched() -> list[dict]:
    f = sched_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_sched(items: list[dict]) -> None:
    write_json_atomic(sched_file(), items, indent=1)


def append_posts_log(entry: dict) -> None:
    with open(STATE_DIR / "_posts.log", "a", encoding="utf-8") as lf:
        lf.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_posts_log(state_dir: Path | None = None) -> list[dict]:
    """_posts.log の各行(壊れた行は飛ばす)。state_dir を渡すと別ボードの分"""
    f = (state_dir or STATE_DIR) / "_posts.log"
    out: list[dict] = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out
