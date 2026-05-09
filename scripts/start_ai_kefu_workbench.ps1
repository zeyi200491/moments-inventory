$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RootDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
$AiKefuConfig = Join-Path $RootDir "config\ai_kefu.yaml"
$FrontendDir = Join-Path $RootDir "frontend\workbench"
$FrontendPackageFile = Join-Path $FrontendDir "package.json"
$LogDir = Join-Path $RootDir ".test-tmp\logs"
$BackendHealthUrl = "http://127.0.0.1:8787/api/health"
$FrontendUrl = "http://127.0.0.1:5173"
$NonInteractive = $env:MOMENTS_INVENTORY_NONINTERACTIVE -eq "1"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message"
}

function Fail-Step {
    param([string]$Message)
    Write-Host "[ERROR] $Message"
    exit 1
}

function Test-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [int]$RetryCount = 60
    )

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        if (Test-HttpReady -Url $Url) {
            Write-Ok "$ServiceName is ready."
            return
        }

        Start-Sleep -Seconds 1
    }

    Fail-Step "$ServiceName did not become ready in time. Check logs: $LogDir"
}

function Ensure-FileExists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        $displayPath = $Path.Replace("$RootDir\", "")
        Fail-Step "Missing $Label file: $displayPath"
    }
}

function Resolve-NpmCommand {
    $command = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        $command = Get-Command npm -ErrorAction SilentlyContinue
    }

    if ($null -eq $command) {
        Fail-Step "npm.cmd was not found. Install Node.js first."
    }

    return $command.Source
}

function Ensure-AiKefuApiKeyEnv {
    param([Parameter(Mandatory = $true)][string]$ConfigPath)

    $configText = Get-Content -LiteralPath $ConfigPath -Raw
    $match = [regex]::Match($configText, '(?m)^\s*api_key_env:\s*["'']?([^"'']+?)["'']?\s*$')
    if (-not $match.Success) {
        return
    }

    $envName = $match.Groups[1].Value.Trim()
    if ([string]::IsNullOrWhiteSpace($envName)) {
        return
    }

    $envValue = [Environment]::GetEnvironmentVariable($envName)
    if ([string]::IsNullOrWhiteSpace($envValue)) {
        Fail-Step "Missing required environment variable: $envName"
    }
}

function Ensure-BackendDependencies {
    Write-Info "Checking backend dependencies..."
    & $PythonExe -c "import uvicorn, fastapi" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Installing backend dependencies..."
        & $PythonExe -m pip install -e $RootDir
        if ($LASTEXITCODE -ne 0) {
            Fail-Step "Failed to install Python dependencies."
        }
    }
}

function Ensure-FrontendDependencies {
    param([Parameter(Mandatory = $true)][string]$NpmCmd)

    $NodeModulesDir = Join-Path $FrontendDir "node_modules"
    if (Test-Path -LiteralPath $NodeModulesDir) {
        return
    }

    Write-Info "Installing frontend dependencies..."
    Push-Location $FrontendDir
    try {
        & $NpmCmd install
        if ($LASTEXITCODE -ne 0) {
            Fail-Step "Failed to install frontend dependencies."
        }
    } finally {
        Pop-Location
    }
}

function Start-BackendIfNeeded {
    if (Test-HttpReady -Url $BackendHealthUrl) {
        Write-Ok "Backend is already running."
        return
    }

    Write-Info "Starting backend service..."
    $backendOutLog = Join-Path $LogDir "backend.out.log"
    $backendErrLog = Join-Path $LogDir "backend.err.log"

    Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "-m", "moments_inventory.cli", "kefu-dev", "--host", "127.0.0.1", "--port", "8787", "--ai-kefu-config", "config/ai_kefu.yaml" `
        -WorkingDirectory $RootDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOutLog `
        -RedirectStandardError $backendErrLog | Out-Null

    Wait-HttpReady -Url $BackendHealthUrl -ServiceName "Backend service"
}

function Start-FrontendIfNeeded {
    param([Parameter(Mandatory = $true)][string]$NpmCmd)

    if (Test-HttpReady -Url $FrontendUrl) {
        Write-Ok "Frontend is already running."
        return
    }

    Write-Info "Starting frontend workbench..."
    $frontendOutLog = Join-Path $LogDir "frontend.out.log"
    $frontendErrLog = Join-Path $LogDir "frontend.err.log"

    Start-Process `
        -FilePath $NpmCmd `
        -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOutLog `
        -RedirectStandardError $frontendErrLog | Out-Null

    Wait-HttpReady -Url $FrontendUrl -ServiceName "Frontend workbench"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Ensure-FileExists -Path $PythonExe -Label ".venv python"
Ensure-FileExists -Path $AiKefuConfig -Label "AI kefu config"
Ensure-FileExists -Path $FrontendPackageFile -Label "frontend package"
Ensure-AiKefuApiKeyEnv -ConfigPath $AiKefuConfig

$npmCmd = Resolve-NpmCommand
Ensure-BackendDependencies
Ensure-FrontendDependencies -NpmCmd $npmCmd
Start-BackendIfNeeded
Start-FrontendIfNeeded -NpmCmd $npmCmd

Write-Ok "Workbench URL: $FrontendUrl"
Write-Ok "Backend health URL: $BackendHealthUrl"
Write-Info "Log directory: $LogDir"

if (-not $NonInteractive) {
    Start-Process $FrontendUrl | Out-Null
}
