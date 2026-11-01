[CmdletBinding()]
param(
  [string]$ConfigPath = '',
  [switch]$Benchmark,
  [switch]$Direct,
  [switch]$ApplyTuning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $PSScriptRoot '..\miner.local'
}
$runnerPath = Join-Path $PSScriptRoot 'pearl_runner.py'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dashboardPath = Join-Path $projectRoot 'dist'
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
  throw "BlockHunter runner was not found at $runnerPath"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
  throw "Miner configuration was not found at $ConfigPath"
}
if (-not $Benchmark -and -not $Direct -and -not (Test-Path -LiteralPath (Join-Path $dashboardPath 'index.html') -PathType Leaf)) {
  throw 'The BlockHunter dashboard is not built. Run npm install and npm run build first.'
}

$localConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$profilePath = Join-Path (Split-Path -Parent $ConfigPath) ([string]$localConfig.profile)
if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
  throw "RTX 4070 profile was not found at $profilePath"
}
$profileConfig = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
$gpuIndex = [int]$profileConfig.gpuIndex
$targetPower = [int]$profileConfig.powerLimitWatts
$targetClock = [int]$profileConfig.lockedCoreClockMHz
$apiPort = [int]$profileConfig.apiPort

if ($ApplyTuning) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = [Security.Principal.WindowsPrincipal]::new($identity)
  $isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $isAdministrator) {
    $elevatedArguments = @(
      '-NoProfile'
      '-ExecutionPolicy', 'Bypass'
      '-File', "`"$PSCommandPath`""
      '-ConfigPath', "`"$ConfigPath`""
      '-ApplyTuning'
    )
    if ($Benchmark) { $elevatedArguments += '-Benchmark' }
    if ($Direct) { $elevatedArguments += '-Direct' }
    $elevated = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $elevatedArguments -Wait -PassThru
    exit $elevated.ExitCode
  }
}

function ConvertTo-WslPath {
  param([Parameter(Mandatory)][string]$WindowsPath)

  $fullPath = [IO.Path]::GetFullPath($WindowsPath)
  if ($fullPath -notmatch '^([A-Za-z]):\\(.*)$') {
    throw "Only local Windows drive paths can be translated to WSL: $fullPath"
  }
  $drive = $Matches[1].ToLowerInvariant()
  $tail = $Matches[2].Replace('\', '/')
  return "/mnt/$drive/$tail"
}

function ConvertTo-NativeArgumentList {
  param([Parameter(Mandatory)][string[]]$Arguments)

  return ($Arguments | ForEach-Object {
    if ($_ -match '\s') {
      '"' + $_.Replace('"', '\"') + '"'
    }
    else {
      $_
    }
  }) -join ' '
}

$runnerWsl = ConvertTo-WslPath -WindowsPath $runnerPath
$configWsl = ConvertTo-WslPath -WindowsPath $ConfigPath
$dashboardWsl = ConvertTo-WslPath -WindowsPath $dashboardPath
$dashboardMode = -not $Benchmark -and -not $Direct

Write-Host ''
Write-Host 'BlockHunter Verified Pearl Mining' -ForegroundColor Cyan
Write-Host '---------------------------------'
Write-Host 'CUDA target:  sm_89 only'
Write-Host "Power target: $targetPower W"
Write-Host "Core target:  $targetClock MHz locked"
Write-Host 'Memory clock: stock'
Write-Host "VRAM reserve: $($profileConfig.vramReserveMiB) MiB"
Write-Host "Local console: http://127.0.0.1:$apiPort"
Write-Host ''
Write-Warning 'Mining consumes electricity and includes the upstream miner 2% developer fee.'
if ($dashboardMode) {
  Write-Host 'Choose Pool or Solo in the browser, then press Start mining.' -ForegroundColor Green
  Write-Host 'Use Stop & restore in the browser, or close this window, to restore GPU settings.' -ForegroundColor Yellow
}

if ($Direct) {
  $confirmation = Read-Host 'Type START to begin direct mining, or press Enter to cancel'
  if ($confirmation -cne 'START') {
    Write-Host 'Cancelled. The miner was not started.' -ForegroundColor Yellow
    exit 0
  }
}

$arguments = @('python3', $runnerWsl, '--config', $configWsl)
if ($Benchmark) {
  $arguments += @('--benchmark', '--benchmark-regions', '64')
}
elseif ($Direct) {
  $arguments += '--mine'
}
else {
  $arguments += @('--serve', '--dashboard-root', $dashboardWsl)
}

$originalPower = $null
$runnerExitCode = 0
$wslProcess = $null
try {
  if ($ApplyTuning) {
    $powerOutput = (& nvidia-smi.exe -i $gpuIndex --query-gpu=power.limit --format=csv,noheader,nounits).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $powerOutput) {
      throw 'Unable to read the current NVIDIA power limit.'
    }
    $originalPower = [int][double]($powerOutput -split '\s+')[0]

    & nvidia-smi.exe -i $gpuIndex -pl $targetPower
    if ($LASTEXITCODE -ne 0) {
      throw "Unable to apply the $targetPower W power limit."
    }
    & nvidia-smi.exe -i $gpuIndex -lgc "$targetClock,$targetClock"
    if ($LASTEXITCODE -ne 0) {
      throw "Unable to lock the core at $targetClock MHz."
    }
    $arguments += '--tuning-preapplied'
    Write-Host "Applied $targetPower W / $targetClock MHz. Settings restore on exit." -ForegroundColor Green
  }

  if ($dashboardMode) {
    $nativeArguments = ConvertTo-NativeArgumentList -Arguments $arguments
    $wslProcess = Start-Process -FilePath 'wsl.exe' -ArgumentList $nativeArguments -NoNewWindow -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
      if ($wslProcess.HasExited) { break }
      try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 1
        if ($health.ok) {
          $ready = $true
          break
        }
      }
      catch {
        Start-Sleep -Milliseconds 500
      }
    }
    if (-not $ready) {
      throw 'BlockHunter did not open its local control service within 30 seconds.'
    }
    Start-Process "http://127.0.0.1:$apiPort"
    $wslProcess.WaitForExit()
    $runnerExitCode = $wslProcess.ExitCode
  }
  else {
    $LASTEXITCODE = 0
    & wsl.exe @arguments
    $runnerExitCode = $LASTEXITCODE
  }
}
finally {
  if ($null -ne $wslProcess -and -not $wslProcess.HasExited) {
    Stop-Process -Id $wslProcess.Id -Force -ErrorAction SilentlyContinue
  }
  if ($ApplyTuning) {
    & nvidia-smi.exe -i $gpuIndex -rgc | Out-Null
    if ($null -ne $originalPower) {
      & nvidia-smi.exe -i $gpuIndex -pl $originalPower | Out-Null
    }
    Write-Host 'Restored the original NVIDIA power and clock settings.' -ForegroundColor Yellow
  }
}

if ($runnerExitCode -ne 0) {
  throw "BlockHunter exited with code $runnerExitCode."
}
