Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

& nvidia-smi.exe --query-gpu=name,driver_version,temperature.gpu,power.draw,power.limit,clocks.current.graphics,utilization.gpu,memory.used,memory.free --format=csv,noheader

Write-Host ''
try {
  $status = Invoke-RestMethod -Uri 'http://127.0.0.1:21550/status' -TimeoutSec 3
  $status | ConvertTo-Json -Depth 6
}
catch {
  Write-Warning "BlockHunter telemetry is not available: $($_.Exception.Message)"
  exit 1
}
