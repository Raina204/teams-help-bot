# ============================================================
# Script Name  : Storage Utilisation Check
# Description  : Reports disk usage for all fixed drives
#                including C: drive details for bot parsing.
# Output Format: KEY=VALUE (one per line) for bot parsing
# Compatible   : Windows 10/11, Windows Server 2016+
# ============================================================

try {
    # Get all fixed drives (DriveType 3 = fixed local disk)
    $drives = Get-WmiObject -Class Win32_LogicalDisk `
              -Filter "DriveType=3" -ErrorAction Stop

    foreach ($drive in $drives) {
        $letter   = $drive.DeviceID -replace ":", ""
        $totalGB  = [math]::Round($drive.Size / 1GB, 1)
        $freeGB   = [math]::Round($drive.FreeSpace / 1GB, 1)
        $usedGB   = [math]::Round($totalGB - $freeGB, 1)
        $pct      = if ($totalGB -gt 0) {
                        [math]::Round(($usedGB / $totalGB) * 100)
                    } else { 0 }

        # Output in format expected by rmm_service.py _parse() function
        Write-Output "DRIVE_${letter}:_USED_PCT=$pct"
        Write-Output "DRIVE_${letter}:_FREE_GB=$freeGB"
        Write-Output "DRIVE_${letter}:_USED_GB=$usedGB"
        Write-Output "DRIVE_${letter}:_TOTAL_GB=$totalGB"
    }

    Write-Output "STATUS=success"
}
catch {
    Write-Output "STATUS=error"
    Write-Output "ERROR=$($_.Exception.Message)"
    exit 1
}
