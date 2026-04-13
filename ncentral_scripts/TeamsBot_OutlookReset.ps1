Get-Process OUTLOOK -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
Start-Process "OUTLOOK.EXE"
Write-Output "Outlook restarted successfully"
