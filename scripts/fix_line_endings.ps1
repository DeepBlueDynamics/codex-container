#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Fix line endings in shell scripts for cross-platform compatibility.

.DESCRIPTION
    Converts CRLF (Windows) line endings to LF (Unix) in shell scripts.
    Essential for scripts that need to run on Mac/Linux.

.PARAMETER Path
    Path to file or directory to fix. Defaults to scripts directory.

.PARAMETER Recursive
    If specified, processes all .sh files recursively.

.EXAMPLE
    .\fix_line_endings.ps1
    Fixes all .sh files in scripts directory

.EXAMPLE
    .\fix_line_endings.ps1 -Path codex_container.sh
    Fixes specific file
#>

param(
    [string]$Path,
    [switch]$Recursive
)

$ErrorActionPreference = "Stop"

# Determine target path
if (-not $Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $Path = $ScriptDir
}

$Path = Resolve-Path $Path -ErrorAction Stop

Write-Host "Fixing line endings for Unix compatibility" -ForegroundColor Cyan
Write-Host "  Target: $Path" -ForegroundColor DarkGray
Write-Host ""

# Find shell scripts
$files = if (Test-Path $Path -PathType Container) {
    if ($Recursive) {
        Get-ChildItem -Path $Path -Filter "*.sh" -File -Recurse
    } else {
        Get-ChildItem -Path $Path -Filter "*.sh" -File
    }
} else {
    @(Get-Item $Path)
}

$fixed = 0
$skipped = 0

foreach ($file in $files) {
    Write-Host "Checking: $($file.Name)" -ForegroundColor Gray -NoNewline

    # Read file as bytes to detect line endings
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $hasCRLF = $false

    for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
        if ($bytes[$i] -eq 13 -and $bytes[$i + 1] -eq 10) {  # CRLF = \r\n = 13,10
            $hasCRLF = $true
            break
        }
    }

    if ($hasCRLF) {
        # Read content and replace CRLF with LF
        $content = [System.IO.File]::ReadAllText($file.FullName)
        $content = $content -replace "`r`n", "`n"  # CRLF -> LF
        $content = $content -replace "`r", "`n"    # CR -> LF (just in case)

        # Write back with LF only
        [System.IO.File]::WriteAllText($file.FullName, $content, [System.Text.UTF8Encoding]::new($false))

        Write-Host " -> Fixed (CRLF -> LF)" -ForegroundColor Green
        $fixed++
    } else {
        Write-Host " -> Already LF" -ForegroundColor DarkGray
        $skipped++
    }
}

Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  Fixed: $fixed files" -ForegroundColor Green
Write-Host "  Skipped: $skipped files (already correct)" -ForegroundColor DarkGray
Write-Host ""

if ($fixed -gt 0) {
    Write-Host "✅ Line endings fixed! Scripts are now Mac/Linux compatible." -ForegroundColor Green
} else {
    Write-Host "✅ All scripts already have correct line endings." -ForegroundColor Green
}
