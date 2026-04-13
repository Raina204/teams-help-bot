$disk    = Get-PSDrive C
$usedGB  = [math]::Round($disk.Used / 1GB, 1)
$freeGB  = [math]::Round($disk.Free / 1GB, 1)
$totalGB = $usedGB + $freeGB
$pct     = [math]::Round(($usedGB / $totalGB) * 100, 1)

Write-Output "DRIVE_C:_USED_PCT=$pct"
Write-Output "DRIVE_C:_FREE_GB=$freeGB"
