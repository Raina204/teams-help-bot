# ============================================================
# Script Name  : CPU Utilisation Check
# Description  : Reports current CPU load percentage and
#                processor details.
# Output Format: KEY=VALUE (one per line) for bot parsing
# Compatible   : Windows 10/11, Windows Server 2016+
# ============================================================

try {
    # Get CPU load percentage (average across all cores)
    $processors = Get-WmiObject -Class Win32_Processor -ErrorAction Stop
    $avgLoad    = [math]::Round(($processors | Measure-Object -Property LoadPercentage -Average).Average)

    # Get processor name
    $cpuName    = ($processors | Select-Object -First 1).Name.Trim()

    # Get number of cores and logical processors
    $cores      = ($processors | Measure-Object -Property NumberOfCores -Sum).Sum
    $logical    = ($processors | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum

    # Get CPU speed in GHz
    $speedMHz   = ($processors | Select-Object -First 1).MaxClockSpeed
    $speedGHz   = [math]::Round($speedMHz / 1000, 2)

    Write-Output "CPU_LOAD_PCT=$avgLoad"
    Write-Output "CPU_NAME=$cpuName"
    Write-Output "CPU_CORES=$cores"
    Write-Output "CPU_LOGICAL_PROCESSORS=$logical"
    Write-Output "CPU_SPEED_GHZ=$speedGHz"
    Write-Output "STATUS=success"
}
catch {
    Write-Output "STATUS=error"
    Write-Output "ERROR=$($_.Exception.Message)"
    exit 1
}
