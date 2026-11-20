"""動画の加工・サムネイル・ダウンロード・クリップボード。"""
import subprocess
from pathlib import Path

import requests


def video_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return float(r.stdout.strip())


def edit_video(src: Path, dest: Path, crop: float, brightness: float, contrast: float, saturation: float,
               head: float = 0.0, tail: float = 0.0) -> None:
    """四辺を crop(0〜0.1 の割合)ずつ切り抜き、明るさ・コントラスト・彩度を調整し、前後を head/tail 秒カットして再エンコード。"""
    crop = min(max(crop, 0.0), 0.10)
    keep = 1 - 2 * crop
    vf = (f"crop=trunc(iw*{keep:.4f}/2)*2:trunc(ih*{keep:.4f}/2)*2,"
          f"eq=brightness={min(max(brightness, -0.3), 0.3):.3f}:contrast={min(max(contrast, 0.5), 2.0):.3f}"
          f":saturation={min(max(saturation, 0.0), 3.0):.3f}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    trim = []
    if head > 0 or tail > 0:
        dur = video_duration(src)
        if dur - head - tail >= 1.0:  # 短すぎる動画は秒数カットしない
            trim = ["-ss", f"{head:.3f}", "-t", f"{dur - head - tail:.3f}"]
    cmd = ["ffmpeg", "-y", "-i", str(src), *trim, "-vf", vf, "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)]
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip().splitlines()[-1] if res.stderr else "ffmpeg failed")


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
    subprocess.run(["osascript", "-e", "on run argv", "-e", "set the clipboard to (POSIX file (item 1 of argv))",
                    "-e", "end run", str(path.resolve())], check=True)


def download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
