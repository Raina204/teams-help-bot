# ============================================================
# Script Name  : Memory Utilisation Check
# Description  : Reports total, used, and free memory in GB
#                along with usage percentage.
# Output Format: KEY=VALUE (one per line) for bot parsing
# Compatible   : Windows 10/11, Windows Server 2016+
# ============================================================

try {
    $os      = Get-WmiObject -Class Win32_OperatingSystem -ErrorAction Stop
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    $freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    $usedGB  = [math]::Round($totalGB - $freeGB, 1)
    $pct     = [math]::Round(($usedGB / $totalGB) * 100)

    Write-Output "MEMORY_USED_PCT=$pct"
    Write-Output "MEMORY_TOTAL_GB=$totalGB"
    Write-Output "MEMORY_USED_GB=$usedGB"
    Write-Output "MEMORY_FREE_GB=$freeGB"
    Write-Output "STATUS=success"
}
catch {
    Write-Output "STATUS=error"
    Write-Output "ERROR=$($_.Exception.Message)"
    exit 1
}
