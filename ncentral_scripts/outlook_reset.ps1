# ============================================================
# Script Name  : Outlook Reset and Refresh
# Description  : Safely closes Outlook, clears the local
#                cache files (.ost/.nst), and restarts
#                Outlook fresh. Fixes common profile,
#                sync, and connectivity issues.
# Output Format: KEY=VALUE (one per line) for bot parsing
# Compatible   : Windows 10/11, Microsoft Outlook 2016+
# ============================================================

try {
    # Step 1 — Check if Outlook is running
    $outlookRunning = Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue

    if ($outlookRunning) {
        Write-Output "STEP=closing_outlook"

        # Attempt graceful close first
        $outlookRunning | ForEach-Object {
            $_.CloseMainWindow() | Out-Null
        }
        Start-Sleep -Seconds 5

        # Force kill if still running
        $stillRunning = Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Stop-Process -Name "OUTLOOK" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
        Write-Output "OUTLOOK_CLOSED=true"
    }
    else {
        Write-Output "OUTLOOK_CLOSED=not_running"
    }

    # Step 2 — Clear Outlook cache files
    Write-Output "STEP=clearing_cache"

    $profilePath = $env:LOCALAPPDATA + '\Microsoft\Outlook'
    $filesCleared = 0

    if (Test-Path $profilePath) {
        # Remove .ost files (offline cached data)
        $ostFiles = Get-ChildItem -Path $profilePath -Filter "*.ost" -ErrorAction SilentlyContinue
        foreach ($file in $ostFiles) {
            try {
                Remove-Item $file.FullName -Force -ErrorAction Stop
                $filesCleared++
            }
            catch {
                # File may be locked - skip silently
            }
        }

        # Remove .nst files (offline group data)
        $nstFiles = Get-ChildItem -Path $profilePath -Filter "*.nst" -ErrorAction SilentlyContinue
        foreach ($file in $nstFiles) {
            try {
                Remove-Item $file.FullName -Force -ErrorAction Stop
                $filesCleared++
            }
            catch {
                # File may be locked - skip silently
            }
        }
    }

    Write-Output "FILES_CLEARED=$filesCleared"

    # Step 3 — Clear Outlook autocomplete cache
    $roamingPath   = $env:APPDATA + '\Microsoft\Outlook'
    $autocomplete  = Get-ChildItem -Path $roamingPath -Filter "*.nk2" -ErrorAction SilentlyContinue
    foreach ($file in $autocomplete) {
        Remove-Item $file.FullName -Force -ErrorAction SilentlyContinue
    }

    # Step 4 — Wait before restarting
    Start-Sleep -Seconds 2

    # Step 5 — Restart Outlook
    Write-Output "STEP=restarting_outlook"

    $outlookPath = ""

    # Check common Outlook installation paths
    $possiblePaths = @(
        "${env:ProgramFiles}\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "${env:ProgramFiles}\Microsoft Office\Office16\OUTLOOK.EXE",
        "${env:ProgramFiles(x86)}\Microsoft Office\Office16\OUTLOOK.EXE",
        "${env:ProgramFiles}\Microsoft Office\Office15\OUTLOOK.EXE",
        "${env:ProgramFiles(x86)}\Microsoft Office\Office15\OUTLOOK.EXE"
    )

    foreach ($path in $possiblePaths) {
        if (Test-Path $path) {
            $outlookPath = $path
            break
        }
    }

    if ($outlookPath) {
        Start-Process -FilePath $outlookPath
        Write-Output "OUTLOOK_RESTARTED=true"
        Write-Output "OUTLOOK_PATH=$outlookPath"
    }
    else {
        # Fallback to generic start
        Start-Process "OUTLOOK.EXE" -ErrorAction SilentlyContinue
        Write-Output "OUTLOOK_RESTARTED=true"
        Write-Output "OUTLOOK_PATH=default"
    }

    Write-Output "OUTLOOK_RESET=success"
    Write-Output "STATUS=success"
}
catch {
    Write-Output "STATUS=error"
    Write-Output "ERROR=$($_.Exception.Message)"
    exit 1
}
