"""OS ごとに違う操作(クリップボード・デスクトップ通知・Xdeck の起動)をまとめる。macOS と Windows に対応。"""
import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
_NOWIN = {"creationflags": 0x08000000} if IS_WIN else {}  # Windows: 黒いコンソール窓を出さない
_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]


def copy_text(text: str) -> None:
    if IS_WIN:
        subprocess.run(_PS + ["[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                       input=text.encode("utf-8"), check=True, **_NOWIN)
    else:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)


def copy_file(path: Path) -> None:
    """ファイル自体をコピーした状態にする(Finder / エクスプローラーでコピーしたのと同じ)"""
    p = str(Path(path).resolve())
    if IS_WIN:
        subprocess.run(_PS + ["Set-Clipboard -LiteralPath $env:XB_PATH"], env={**os.environ, "XB_PATH": p}, check=True, **_NOWIN)
    else:
        subprocess.run(["osascript", "-e", "on run argv", "-e", "set the clipboard to (POSIX file (item 1 of argv))",
                        "-e", "end run", p], check=True)


def desktop_notify(title: str, text: str) -> None:
    """Discord に送れないときの代わりの、デスクトップ通知(失敗しても例外は出さない)"""
    msg = text.replace("\n", " ")[:180]
    try:
        if IS_WIN:
            script = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
                      "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
                      "$n.ShowBalloonTip(8000,$env:XB_T,$env:XB_M,'Info'); Start-Sleep -Seconds 9; $n.Dispose()")
            subprocess.Popen(_PS + [script], env={**os.environ, "XB_T": title, "XB_M": msg}, **_NOWIN)  # 待たない
        elif IS_MAC:
            subprocess.run(["osascript", "-e", f'display notification "{msg.replace(chr(34), chr(39)).replace(chr(92), " ")}" with title "{title}"'],
                           check=False, capture_output=True)
    except Exception as e:  # noqa: BLE001
        print("notify error:", str(e)[:100])


def launch_xdeck() -> bool:
    """Xdeck アプリを起動する。Windows は .env の XDECK_EXE(XDeck.exe のフルパス)、なければよくある場所を探す"""
    try:
        if IS_MAC:
            subprocess.run(["open", "-a", "XDeck"], check=False, capture_output=True)
            return True
        if IS_WIN:
            la, pf = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")
            cands = [os.environ.get("XDECK_EXE", ""), f"{la}\\Programs\\XDeck\\XDeck.exe", f"{la}\\XDeck\\XDeck.exe", f"{pf}\\XDeck\\XDeck.exe"]
            exe = next((c for c in cands if c and Path(c).exists()), "")
            if exe:
                os.startfile(exe)  # type: ignore[attr-defined]
                return True
            print("Xdeck の場所が見つかりません。.env に XDECK_EXE=<XDeck.exe のフルパス> を書いてください")
    except Exception as e:  # noqa: BLE001
        print("xdeck launch error:", str(e)[:100])
    return False
