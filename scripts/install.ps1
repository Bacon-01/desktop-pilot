param(
    [string]$ProjectRoot = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Write-Json($Object) {
    [Console]::Out.Write(($Object | ConvertTo-Json -Depth 6 -Compress))
}

try {
    if (-not $ProjectRoot) {
        $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
    }
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $skillFile = Join-Path $ProjectRoot "SKILL.md"
    if (-not (Test-Path -LiteralPath $skillFile)) {
        Write-Json @{ ok = $false; error = "SKILL.md not found in project root"; project = $ProjectRoot }
        exit 2
    }

    $skillRoot = Join-Path $env:USERPROFILE ".dsh\skills"
    New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
    $link = Join-Path $skillRoot "desktop-pilot"
    $backup = $null

    if (Test-Path -LiteralPath $link) {
        $item = Get-Item -LiteralPath $link -Force
        $isReparse = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        $probe = Join-Path $link "SKILL.md"
        $pointsHere = $false
        if ($isReparse -and $item.Target) {
            $normalizedProject = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
            foreach ($t in @($item.Target)) {
                try {
                    if ([System.IO.Path]::GetFullPath($t).TrimEnd('\') -ieq $normalizedProject) {
                        $pointsHere = $true
                    }
                } catch {
                    # ignore malformed link targets
                }
            }
        }
        if ($pointsHere) {
            $runtimeDir = Join-Path $ProjectRoot "runtime"
            New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
            @{
                installed_at = (Get-Date).ToString("o")
                project = $ProjectRoot
                link = $link
                skill = $skillFile
                backup = $null
                user = $env:USERNAME
            } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtimeDir "install.json") -Encoding UTF8
            Write-Json @{
                ok = $true
                already = $true
                link = $link
                project = $ProjectRoot
                skill = $skillFile
                message = "skill junction already points at this project"
            }
            exit 0
        }
        if (-not $Force) {
            Write-Json @{
                ok = $false
                error = "target already exists and does not point at this project; pass -Force to replace it"
                link = $link
                reparse = $isReparse
                project = $ProjectRoot
            }
            exit 3
        }
        $backup = "$link.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Move-Item -LiteralPath $link -Destination $backup -Force
    }

    New-Item -ItemType Junction -Path $link -Target $ProjectRoot | Out-Null

    $probe = Join-Path $link "SKILL.md"
    if (-not (Test-Path -LiteralPath $probe)) {
        Write-Json @{ ok = $false; error = "junction created but SKILL.md is not visible through it"; link = $link; project = $ProjectRoot }
        exit 4
    }
    $created = Get-Item -LiteralPath $link -Force
    $normalizedProject = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $resolved = $null
    foreach ($t in @($created.Target)) {
        try {
            if ([System.IO.Path]::GetFullPath($t).TrimEnd('\') -ieq $normalizedProject) {
                $resolved = $t
            }
        } catch {
            # ignore malformed link targets
        }
    }
    if (-not $resolved) {
        Write-Json @{ ok = $false; error = "junction resolves to the wrong target"; link = $link; target = $created.Target; expected = $ProjectRoot }
        exit 5
    }

    $record = @{
        installed_at = (Get-Date).ToString("o")
        project = $ProjectRoot
        link = $link
        skill = $skillFile
        backup = $backup
        user = $env:USERNAME
    }
    $runtimeDir = Join-Path $ProjectRoot "runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtimeDir "install.json") -Encoding UTF8

    Write-Json @{
        ok = $true
        already = $false
        link = $link
        project = $ProjectRoot
        skill = $skillFile
        backup = $backup
        message = "installed as a DSH skill junction; new DSH sessions will discover it"
    }
} catch {
    Write-Json @{ ok = $false; error = $_.Exception.Message; detail = $_.ScriptStackTrace }
    exit 1
}