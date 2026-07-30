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


def test_start_ps1_uses_app_serve_module_entrypoint() -> None:
    content = (ROOT / "start.ps1").read_text(encoding="utf-8").lower()

    assert "-m app.serve" in content


def test_readme_uses_app_serve_module_entrypoint() -> None:
    content = (ROOT / "README.md").read_text(encoding="utf-8")

    assert content.count("-m app.serve") >= 2
    assert "uvicorn app.api.main:app" not in content
    assert "SelectorEventLoop" in content


def test_start_bat_uses_its_own_directory_and_preserves_errors() -> None:
    content = (ROOT / "start.bat").read_text(encoding="utf-8").lower()

    assert 'cd /d "%~dp0"' in content
    assert "-executionpolicy bypass" in content
    assert '-file "%~dp0start.ps1"' in content
    assert "if errorlevel 1" in content
    assert "pause" in content
