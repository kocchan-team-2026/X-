# Windows 用: ログイン時に Xdeck とボードを自動で起動するタスクを登録する(管理者権限は不要)
#   登録: .\scripts\autostart.ps1      解除: Unregister-ScheduledTask -TaskName XBoard -Confirm:$false
$bat = Join-Path $PSScriptRoot "start.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"   # Xdeck が立ち上がるのを少し待つ
Register-ScheduledTask -TaskName "XBoard" -Action $action -Trigger $trigger -Force | Out-Null
Write-Host "登録しました。次回のログインから、ボードが自動で起動します(Xdeck も、スタートアップに入れておいてください)"
