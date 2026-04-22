$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
Write-Output "CPU_LOAD_PCT=$cpu"
