# Windows 用セットアップ: PowerShell で  .\scripts\setup.ps1  を実行する
# 1) Python の仮想環境と依存パッケージ  2) ffmpeg / Python の確認(なければ winget で導入)  3) .env の確認
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Has($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

if (-not (Has "python")) {
    Write-Host "Python が見つかりません。winget で入れます(入れたあと、この PowerShell を開き直して、もう一度実行してください)"
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    exit 0
}
if (-not (Has "ffmpeg")) {
    Write-Host "ffmpeg を入れます(動画の加工・サムネイルに必要)"
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    Write-Host "→ 入れたあとは PowerShell を開き直してください(PATH を読み直すため)"
}
if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q -U pip
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
Write-Host "依存パッケージ: OK"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env を作りました。メモ帳で開いて、トークンなどを入力してください: notepad .env"
} else { Write-Host ".env: OK" }
if (Has "claude") { Write-Host "claude (Claude Code): OK" } else { Write-Host "claude: 見つかりません(任意。本文リライト機能だけに使います)" }
Write-Host "`n次の手順: Xdeck を起動してログインし、.env の XDECK_TOKEN を設定 → .\scripts\start.bat"
