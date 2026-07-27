# Windows One-Click Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a double-click Windows launcher that validates the local environment, applies database migrations, opens visible backend and frontend terminals, waits for readiness, and opens the frontend in the default browser.

**Architecture:** `start.bat` is the stable double-click entry point and delegates to `start.ps1`. The PowerShell script owns validation and orchestration, while a side-effect-free `-CheckOnly` mode makes the launcher testable without starting services, migrating the database, or opening a browser.

**Tech Stack:** Windows PowerShell 5.1+, Batch, Python 3.11+, pytest, FastAPI/Uvicorn, Node.js/npm, Vite

## Global Constraints

- Keep FastAPI and Vite as the existing backend and frontend processes.
- Use the repository `.venv\Scripts\python.exe`; do not create a second environment.
- Run `python -m app.db.migrate` before starting either service.
- Use backend port `8000` and frontend port `5173`.
- Open two visible terminals titled `Career-RAG Backend` and `Career-RAG Frontend`.
- Open `http://127.0.0.1:5173` only after both services report ready.
- Do not install packages, change `.env`, call model APIs, or add background service managers.
- Do not alter application state management, concurrency, retrieval, or Agent code.
- Do not commit changes unless the user explicitly requests a commit.

## File Structure

- Create `tests/test_windows_launcher.py`: launcher contract, parsing, and side-effect-free check-mode tests.
- Create `start.ps1`: environment validation, migration, visible child terminals, readiness polling, and browser launch.
- Create `start.bat`: double-click wrapper that resolves the repository directory and preserves errors for the user.

---

### Task 1: PowerShell launcher with check-only mode

**Files:**
- Create: `tests/test_windows_launcher.py`
- Create: `start.ps1`

**Interfaces:**
- Consumes: `.env`, `.venv\Scripts\python.exe`, `frontend\package.json`, `frontend\node_modules`, `npm.cmd`, `app.db.migrate`, `app.api.main:app`
- Produces: `start.ps1 [-CheckOnly]`; check mode prints `CHECK_OK`, `backend=http://127.0.0.1:8000`, and `frontend=http://127.0.0.1:5173`

- [ ] **Step 1: Write failing tests for parsing and check-only behavior**

Create `tests/test_windows_launcher.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = "powershell.exe"


def run_powershell(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_start_ps1_is_valid_powershell() -> None:
    command = (
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::"
        "ParseFile((Resolve-Path 'start.ps1'), [ref]$null, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )

    result = run_powershell("-Command", command)

    assert result.returncode == 0, result.stderr


def test_check_only_validates_without_starting_services() -> None:
    result = run_powershell(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "start.ps1"),
        "-CheckOnly",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "CHECK_OK" in output
    assert "backend=http://127.0.0.1:8000" in output
    assert "frontend=http://127.0.0.1:5173" in output
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_windows_launcher.py -q
```

Expected: both tests fail because `start.ps1` does not exist.

- [ ] **Step 3: Implement the minimal PowerShell launcher**

Create `start.ps1`:

```powershell
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
```

- [ ] **Step 4: Ensure Windows PowerShell reads Chinese text correctly**

Run this encoding-only formatting command after `apply_patch` creates `start.ps1`:

```powershell
$content = Get-Content -Raw -Encoding UTF8 start.ps1
Set-Content -LiteralPath start.ps1 -Value $content -Encoding UTF8
```

Expected: `start.ps1` begins with a UTF-8 BOM and Windows PowerShell 5.1 displays Chinese messages correctly.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_windows_launcher.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Inspect process and port state after check mode**

Run:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
```

Expected: no listeners created by the test. If unrelated listeners existed before testing, the check-only test must have failed before creating any process.

### Task 2: Double-click BAT entry point

**Files:**
- Modify: `tests/test_windows_launcher.py`
- Create: `start.bat`

**Interfaces:**
- Consumes: `start.ps1`
- Produces: double-clickable `start.bat` that invokes the sibling PowerShell script from any current working directory and pauses only after errors

- [ ] **Step 1: Add a failing BAT contract test**

Append to `tests/test_windows_launcher.py`:

```python
def test_start_bat_uses_its_own_directory_and_preserves_errors() -> None:
    content = (ROOT / "start.bat").read_text(encoding="utf-8").lower()

    assert 'cd /d "%~dp0"' in content
    assert '-executionpolicy bypass' in content
    assert '-file "%~dp0start.ps1"' in content
    assert "if errorlevel 1" in content
    assert "pause" in content
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_windows_launcher.py::test_start_bat_uses_its_own_directory_and_preserves_errors -q
```

Expected: FAIL with `FileNotFoundError` because `start.bat` does not exist.

- [ ] **Step 3: Implement the BAT wrapper**

Create `start.bat`:

```bat
@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo Career-RAG failed to start. Review the error above.
    pause
)

endlocal
```

- [ ] **Step 4: Run launcher tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_windows_launcher.py -q
```

Expected:

```text
3 passed
```

### Task 3: Full verification and handoff

**Files:**
- Verify: `start.bat`
- Verify: `start.ps1`
- Verify: `tests/test_windows_launcher.py`
- Verify: `docs/superpowers/specs/2026-07-27-one-click-windows-launcher-design.md`

**Interfaces:**
- Consumes: completed launcher files
- Produces: fresh evidence that the launcher contract works and no check-mode side effects remain

- [ ] **Step 1: Run the focused launcher tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_windows_launcher.py -q
```

Expected: `3 passed`.

- [ ] **Step 2: Run the complete Python regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run PowerShell check mode directly**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -CheckOnly
```

Expected:

```text
CHECK_OK
backend=http://127.0.0.1:8000
frontend=http://127.0.0.1:5173
```

- [ ] **Step 4: Review the exact diff**

Run:

```powershell
git diff -- start.bat start.ps1 tests/test_windows_launcher.py docs/superpowers/specs/2026-07-27-one-click-windows-launcher-design.md docs/superpowers/plans/2026-07-27-one-click-windows-launcher.md
```

Expected: only the approved launcher, tests, specification, and implementation plan appear.

- [ ] **Step 5: Report usage without committing**

Tell the user to double-click `start.bat`, or run:

```powershell
.\start.bat
```

Also report that each service remains in its own visible window and can be stopped with `Ctrl+C`.
