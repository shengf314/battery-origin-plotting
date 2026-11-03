param(
    [ValidateSet('Check', 'Sync', 'Release', 'Status')]
    [string]$Action = 'Check',
    [string]$Version,
    [string]$NotesFile,
    [string]$Python = 'python',
    [string]$SourceDir,
    [string]$ReleaseRepo = (Join-Path $env:USERPROFILE '.codex\skill-publishing\battery-origin-plotting')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $SourceDir) {
    $skillConfigRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $SourceDir = Join-Path $skillConfigRoot 'skills\battery-origin-plotting'
}
if (-not (Test-Path -LiteralPath (Join-Path $ReleaseRepo 'scripts\maintain.py'))) {
    throw 'Public checkout missing. Follow references/maintenance.md to clone and initialize it.'
}
if ($Action -eq 'Release') {
    if (-not $Version -or -not $NotesFile) { throw 'Release needs -Version X.Y.Z -NotesFile <UTF-8 Markdown file>.' }
    $NotesFile = (Resolve-Path -LiteralPath $NotesFile).Path
}
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path
Push-Location -LiteralPath $ReleaseRepo
try {
    if ($Action -eq 'Status') {
        & gh run list --repo shengf314/battery-origin-plotting --limit 5
        if ($LASTEXITCODE -ne 0) { throw 'Unable to read GitHub Actions.' }
        & gh release view --repo shengf314/battery-origin-plotting --json tagName,url,isDraft
        if ($LASTEXITCODE -ne 0) { throw 'Unable to read the latest release.' }
    } else {
        $pythonArgs = @('-X', 'utf8', 'scripts/maintain.py')
        switch ($Action) {
            'Check' { $pythonArgs += @('sync', '--source', $SourceDir, '--dry-run') }
            'Sync' { $pythonArgs += @('sync', '--source', $SourceDir, '--push') }
            'Release' { $pythonArgs += @('release', '--source', $SourceDir, '--version', $Version, '--notes-file', $NotesFile) }
        }
        & $Python @pythonArgs
        if ($LASTEXITCODE -ne 0) { throw 'Maintenance stopped. Review the reported files; no force overwrite is performed.' }
    }
} finally {
    Pop-Location
}
