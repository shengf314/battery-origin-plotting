# Publication Plot Rendering Pipeline asset (generic, not task specific).
#
# Converts text into vector glyph outlines and returns them as SVG path data.
# This is the confirmed workaround for the Origin 2024 SVG text export defect
# (spurious overline on text objects containing superscript/subscript
# characters).  Driven purely by data: one request JSON in, one result JSON out.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File render_text_outlines.ps1 -Request request.json
#
# request.json : {"font":"Arial","items":[{"name":"VX","text":"...","size_pt":7,"rotation_deg":0}]}
# result  json : {"items":[{"name":"VX","path_d":"...","width_pt":29.3,"height_pt":2.32}]}

param(
    [Parameter(Mandatory = $true)][string]$Request
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$payload = Get-Content -Raw -Encoding UTF8 -LiteralPath $Request | ConvertFrom-Json
$fontName = if ($payload.font) { [string]$payload.font } else { 'Arial' }
$family = New-Object System.Drawing.FontFamily($fontName)
$results = @()

foreach ($item in $payload.items) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $style = [System.Drawing.FontStyle]::Regular
    $format = [System.Drawing.StringFormat]::GenericTypographic
    $origin = [System.Drawing.PointF]::new(0, 0)
    $path.AddString([string]$item.text, $family, [int]$style, [single]$item.size_pt, $origin, $format)
    if ($item.rotation_deg -and [double]$item.rotation_deg -ne 0) {
        $matrix = New-Object System.Drawing.Drawing2D.Matrix
        $matrix.Rotate([single][double]$item.rotation_deg)
        $path.Transform($matrix)
        $matrix.Dispose()
    }
    $bounds = $path.GetBounds()
    $normalise = New-Object System.Drawing.Drawing2D.Matrix
    $normalise.Translate(-$bounds.X, -$bounds.Y)
    $path.Transform($normalise)
    $normalise.Dispose()

    $points = $path.PathPoints
    $types = $path.PathTypes
    $builder = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $points.Count; $i++) {
        $kind = $types[$i] -band 7
        if ($kind -eq 0) {
            [void]$builder.Append("M $($points[$i].X),$($points[$i].Y) ")
        }
        elseif ($kind -eq 1) {
            [void]$builder.Append("L $($points[$i].X),$($points[$i].Y) ")
        }
        elseif ($kind -eq 3) {
            [void]$builder.Append("C $($points[$i].X),$($points[$i].Y) $($points[$i + 1].X),$($points[$i + 1].Y) $($points[$i + 2].X),$($points[$i + 2].Y) ")
            $i += 2
        }
        if ($types[$i] -band 128) {
            [void]$builder.Append('Z ')
        }
    }
    $results += [pscustomobject]@{
        name      = [string]$item.name
        text      = [string]$item.text
        path_d    = $builder.ToString().Trim()
        width_pt  = [double]$bounds.Width
        height_pt = [double]$bounds.Height
    }
    $path.Dispose()
}

$family.Dispose()
$result = [pscustomobject]@{ font = $fontName; items = $results }
$outPath = if ($payload.out_json) { [string]$payload.out_json } else { [System.IO.Path]::ChangeExtension($Request, '.out.json') }
$json = $result | ConvertTo-Json -Depth 5 -Compress
[System.IO.File]::WriteAllText($outPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output $outPath
