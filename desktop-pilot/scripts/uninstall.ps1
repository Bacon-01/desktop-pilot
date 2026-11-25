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
    $link = Join-Path $env:USERPROFILE ".dsh\skills\desktop-pilot"

    if (-not (Test-Path -LiteralPath $link)) {
        Write-Json @{ ok = $true; removed = $false; message = "skill junction does not exist"; link = $link }
        exit 0
    }

    $item = Get-Item -LiteralPath $link -Force
    $isReparse = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
    $pointsHere = $false
    $normalizedProject = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    if ($isReparse -and $item.Target) {
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
    if (-not $pointsHere) {
        $probe = Join-Path $link "SKILL.md"
        if (Test-Path -LiteralPath $probe) {
            try {
                $resolvedProbe = (Resolve-Path -LiteralPath $probe).Path
                $expectedProbe = (Resolve-Path -LiteralPath $skillFile).Path
                $pointsHere = ($resolvedProbe -ieq $expectedProbe)
            } catch {
                $pointsHere = $false
            }
        }
    }

    if (-not $pointsHere -and -not $Force) {
        Write-Json @{
            ok = $false
            error = "refusing to remove a path that does not resolve to this project; pass -Force only if you are sure"
            link = $link
            reparse = $isReparse
        }
        exit 3
    }

    # Removing a junction removes the link, never the target contents.
    $target = $null
    try { $target = (Get-Item -LiteralPath $link -Force).Target } catch { $target = $null }
    & cmd.exe /d /c "rd `"$link`"" | Out-Null
    if (Test-Path -LiteralPath $link) {
        throw "rd returned but the junction still exists"
    }

    Write-Json @{
        ok = $true
        removed = $true
        link = $link
        project = $ProjectRoot
        target = $target
        message = "skill junction removed; project files were not touched"
    }
} catch {
    Write-Json @{ ok = $false; error = $_.Exception.Message; detail = $_.ScriptStackTrace }
    exit 1
}