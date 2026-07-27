[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$BackendUrl = "http://127.0.0.1:8000"
$FrontendUrl = "http://127.0.0.1:5173"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$FrontendRoot = Join-Path $ProjectRoot "frontend"

function Stop-Launcher {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host ""
    Write-Host "[启动失败] $Message" -ForegroundColor Red
    exit 1
}

function Assert-RequiredPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Stop-Launcher $Message
    }
}

function Test-LocalPortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $Port
    )
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        $listener.Stop()
    }
}

function ConvertTo-EncodedPowerShellCommand {
    param([Parameter(Mandatory = $true)][string]$Command)

    return [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($Command)
    )
}

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [int]$TimeoutSeconds = 60
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "[就绪] $ServiceName" -ForegroundColor Green
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    Stop-Launcher "$ServiceName 在 $TimeoutSeconds 秒内未就绪。请检查对应终端窗口。"
}

Assert-RequiredPath `
    -Path (Join-Path $ProjectRoot ".env") `
    -Message "缺少 .env。请复制 .env.example 为 .env 并填写配置。"
Assert-RequiredPath `
    -Path $PythonPath `
    -Message "缺少项目虚拟环境。请创建 .venv 并安装 requirements.txt。"
Assert-RequiredPath `
    -Path (Join-Path $FrontendRoot "package.json") `
    -Message "缺少 frontend\package.json。"
Assert-RequiredPath `
    -Path (Join-Path $FrontendRoot "node_modules") `
    -Message "缺少前端依赖。请在 frontend 目录运行 npm.cmd install。"

$NpmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($null -eq $NpmCommand) {
    Stop-Launcher "找不到 npm.cmd。请安装 Node.js。"
}

foreach ($port in @(8000, 5173)) {
    if (-not (Test-LocalPortAvailable -Port $port)) {
        Stop-Launcher "端口 $port 已被占用。请先关闭占用该端口的程序。"
    }
}

if ($CheckOnly) {
    Write-Output "CHECK_OK"
    Write-Output "backend=$BackendUrl"
    Write-Output "frontend=$FrontendUrl"
    exit 0
}

Write-Host "[1/4] 正在应用数据库迁移..." -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & $PythonPath -m app.db.migrate
    if ($LASTEXITCODE -ne 0) {
        Stop-Launcher "数据库迁移失败。请检查 PostgreSQL、pgvector 和 .env。"
    }
}
finally {
    Pop-Location
}

$escapedProjectRoot = $ProjectRoot.Replace("'", "''")
$escapedFrontendRoot = $FrontendRoot.Replace("'", "''")
$escapedPythonPath = $PythonPath.Replace("'", "''")

$backendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'Career-RAG Backend'
Set-Location -LiteralPath '$escapedProjectRoot'
& '$escapedPythonPath' -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
"@

$frontendCommand = @"
`$Host.UI.RawUI.WindowTitle = 'Career-RAG Frontend'
Set-Location -LiteralPath '$escapedFrontendRoot'
& npm.cmd run dev
"@

Write-Host "[2/4] 正在打开后端终端..." -ForegroundColor Cyan
Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-EncodedCommand",
        (ConvertTo-EncodedPowerShellCommand $backendCommand)
    )

Write-Host "[3/4] 正在打开前端终端..." -ForegroundColor Cyan
Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-EncodedCommand",
        (ConvertTo-EncodedPowerShellCommand $frontendCommand)
    )

Wait-ForUrl -Url "$BackendUrl/docs" -ServiceName "FastAPI 后端"
Wait-ForUrl -Url $FrontendUrl -ServiceName "Vite 前端"

Write-Host "[4/4] 正在打开浏览器..." -ForegroundColor Cyan
Start-Process $FrontendUrl
Write-Host "Career-RAG 已启动。关闭服务请在对应终端按 Ctrl+C。" -ForegroundColor Green

