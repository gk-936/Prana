<#
.SYNOPSIS
    Starts the PRANA backend (uvicorn) and exposes it publicly via Tailscale
    Funnel, so Twilio's WhatsApp webhook can reach it.

.DESCRIPTION
    - Activates the project's .venv
    - Starts the FastAPI backend on port 8000 (background job)
    - Starts Tailscale Funnel forwarding port 8000 (background job)
    - Waits for both to be healthy and prints the public webhook URL
    - Press Ctrl+C to stop; both processes are cleaned up on exit.

.PARAMETER Port
    Local port for the backend (default 8000).

.EXAMPLE
    .\scripts\start_all.ps1
#>

param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Virtualenv python not found at $Python. Create it with: python -m venv .venv; .\.venv\Scripts\pip install -e ."
}

# Locate tailscale.exe (PATH, or the default install location)
$Tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $Tailscale) {
    $candidate = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $candidate) { $Tailscale = $candidate }
}
if (-not $Tailscale) {
    Write-Error "tailscale.exe not found. Install Tailscale or add it to PATH."
}

$backendJob = $null
$funnelJob = $null

function Stop-All {
    Write-Host "`nStopping..." -ForegroundColor Yellow
    if ($funnelJob)  { Stop-Job $funnelJob  -ErrorAction SilentlyContinue; Remove-Job $funnelJob  -Force -ErrorAction SilentlyContinue }
    if ($backendJob) { Stop-Job $backendJob -ErrorAction SilentlyContinue; Remove-Job $backendJob -Force -ErrorAction SilentlyContinue }
    # Belt-and-suspenders: kill any stray uvicorn for this project and reset funnel.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*uvicorn*backend.main*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    & $Tailscale funnel reset 2>$null
    Write-Host "Stopped backend and funnel." -ForegroundColor Green
}

try {
    Write-Host "Starting PRANA backend on port $Port..." -ForegroundColor Cyan
    $backendJob = Start-Job -ScriptBlock {
        param($py, $root, $port)
        Set-Location $root
        & $py -m uvicorn backend.main:app --host 0.0.0.0 --port $port
    } -ArgumentList $Python, $ProjectRoot, $Port

    # Wait for the backend health endpoint.
    $healthy = $false
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $healthy = $true; break }
        } catch { }
    }
    if (-not $healthy) {
        Write-Host "Backend did not become healthy. Recent output:" -ForegroundColor Red
        Receive-Job $backendJob
        Stop-All
        exit 1
    }
    Write-Host "Backend healthy at http://127.0.0.1:$Port" -ForegroundColor Green

    Write-Host "Starting Tailscale Funnel for port $Port..." -ForegroundColor Cyan
    $funnelJob = Start-Job -ScriptBlock {
        param($ts, $port)
        & $ts funnel $port
    } -ArgumentList $Tailscale, $Port

    Start-Sleep -Seconds 4
    # Derive the public URL from this node's tailnet DNS name.
    $status = & $Tailscale status --json 2>$null | ConvertFrom-Json
    $dns = $status.Self.DNSName.TrimEnd('.')
    if ($dns) {
        $publicUrl = "https://$dns"
        Write-Host ""
        Write-Host "  Public base URL : $publicUrl" -ForegroundColor Green
        Write-Host "  Twilio webhook  : $publicUrl/webhook/whatsapp" -ForegroundColor Green
        Write-Host ""
        Write-Host "  -> Set this as 'WHEN A MESSAGE COMES IN' (POST) in the Twilio" -ForegroundColor Yellow
        Write-Host "     sandbox settings, and as WHATSAPP_WEBHOOK_BASE_URL in .env" -ForegroundColor Yellow
        Write-Host "     (=$publicUrl), then restart if you changed .env." -ForegroundColor Yellow
    } else {
        Write-Host "Funnel started but could not resolve the public DNS name; run 'tailscale funnel status'." -ForegroundColor Yellow
    }

    Write-Host "`nRunning. Press Ctrl+C to stop both.`n" -ForegroundColor Cyan
    # Stream backend logs until interrupted.
    while ($true) {
        Receive-Job $backendJob | ForEach-Object { Write-Host $_ }
        if ($backendJob.State -eq 'Failed' -or $backendJob.State -eq 'Completed') {
            Write-Host "Backend job ended unexpectedly." -ForegroundColor Red
            break
        }
        Start-Sleep -Milliseconds 800
    }
}
finally {
    Stop-All
}
