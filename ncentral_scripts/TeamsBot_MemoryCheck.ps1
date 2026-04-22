$os      = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$usedGB  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
$pct     = [math]::Round(($usedGB / $totalGB) * 100, 1)

Write-Output "MEMORY_USED_PCT=$pct"
Write-Output "MEMORY_TOTAL_GB=$totalGB"
Write-Output "MEMORY_USED_GB=$usedGB"
