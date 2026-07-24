Add-Type -AssemblyName System.Drawing

$out = 'D:\Chef_Vision\output\patent_figures\fig2_rgb_ir_data_acquisition_mapping.png'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null

function U($hex) {
    $chars = New-Object System.Collections.Generic.List[char]
    foreach ($h in ($hex -split ' ')) {
        if ($h.Trim().Length -gt 0) {
            $chars.Add([char][Convert]::ToInt32($h, 16))
        }
    }
    return -join $chars
}

$w = 1800
$h = 1380
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$g.Clear([System.Drawing.Color]::White)

$fontName = 'Microsoft YaHei'
$font = New-Object System.Drawing.Font($fontName, 22, [System.Drawing.FontStyle]::Regular)
$smallFont = New-Object System.Drawing.Font($fontName, 17, [System.Drawing.FontStyle]::Regular)
$tinyFont = New-Object System.Drawing.Font($fontName, 15, [System.Drawing.FontStyle]::Regular)

$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(40,40,40), 3)
$dashPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(110,110,110), 2)
$dashPen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
$brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(30,30,30))
$fill = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(252,252,252))
$softFill = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(248,248,248))

function Draw-Box($x, $y, $bw, $bh, $text, $f=$font, $fillBrush=$fill, $borderPen=$pen) {
    $rect = New-Object System.Drawing.RectangleF($x,$y,$bw,$bh)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $r = 12
    $path.AddArc($x, $y, $r*2, $r*2, 180, 90)
    $path.AddArc($x+$bw-$r*2, $y, $r*2, $r*2, 270, 90)
    $path.AddArc($x+$bw-$r*2, $y+$bh-$r*2, $r*2, $r*2, 0, 90)
    $path.AddArc($x, $y+$bh-$r*2, $r*2, $r*2, 90, 90)
    $path.CloseFigure()
    $script:g.FillPath($fillBrush, $path)
    $script:g.DrawPath($borderPen, $path)

    $sf = New-Object System.Drawing.StringFormat
    $sf.Alignment = [System.Drawing.StringAlignment]::Center
    $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
    $script:g.DrawString($text, $f, $script:brush, $rect, $sf)
    $path.Dispose()
    $sf.Dispose()
}

function Draw-Arrow($x1,$y1,$x2,$y2,$p=$pen) {
    $arrowPen = $p.Clone()
    $cap = New-Object System.Drawing.Drawing2D.AdjustableArrowCap(6, 7, $true)
    $arrowPen.CustomEndCap = $cap
    $script:g.DrawLine($arrowPen, $x1,$y1,$x2,$y2)
    $cap.Dispose()
    $arrowPen.Dispose()
}

function Draw-PolylineArrow($pts, $p=$pen) {
    if ($pts.Count -lt 4) { return }
    for ($i=0; $i -lt $pts.Count-4; $i+=2) {
        $script:g.DrawLine($p, $pts[$i], $pts[$i+1], $pts[$i+2], $pts[$i+3])
    }
    Draw-Arrow $pts[$pts.Count-4] $pts[$pts.Count-3] $pts[$pts.Count-2] $pts[$pts.Count-1] $p
}

$tModule = 'RGB-IR ' + (U '96C6 6210 91C7 96C6 6A21 7EC4')
$tRgbUnit = 'RGB ' + (U '53EF 89C1 5149 56FE 50CF 91C7 96C6 5355 5143') + "`n" + (U '83B7 53D6 56FE 50CF 5E27') + ' / ' + (U '89C6 9891 5E27')
$tIrUnit = 'IR ' + (U '7EA2 5916 6E29 5EA6 77E9 9635 91C7 96C6 5355 5143') + "`n" + (U '8F93 51FA 5B8C 6574 4E8C 7EF4 6E29 5EA6 77E9 9635')
$tScene = (U '9505 5185 70F9 996A 533A 57DF') + "`n" + (U '98DF 6750') + ' / ' + (U '9505 5E95') + ' / ' + (U '9505 58C1') + ' / ' + (U '6405 62CC 7ED3 6784')
$tRgbCoord = 'RGB ' + (U '56FE 50CF 5750 6807 7CFB') + "`n" + (U '63D0 4F9B 8F6E 5ED3 3001 8FD0 52A8 3001 8BED 4E49 4FE1 606F')
$tIrCoord = 'IR ' + (U '6E29 5EA6 77E9 9635 5750 6807 7CFB') + "`n" + (U '63D0 4F9B 9762 72B6 6E29 5EA6 5206 5E03')
$tSync = (U '65F6 95F4 540C 6B65 6A21 5757') + "`n" + (U '65F6 95F4 6233 5339 914D') + ' / ' + (U '6700 8FD1 5E27 5339 914D') + ' / ' + (U '7F13 5B58 961F 5217 5339 914D')
$tMap = (U '7A7A 95F4 914D 51C6 4E0E 6807 5B9A 6620 5C04 6A21 5757') + "`n" + (U '900F 89C6 53D8 6362') + ' / ' + (U '51E0 4F55 6620 5C04') + ' / ' + (U '67E5 627E 8868 6620 5C04')
$tRgbMask = 'RGB ' + (U '98DF 6750 533A 57DF') + ' / ' + (U '5019 9009 533A 57DF') + "`n" + (U '53EF 6620 5C04 81F3') + ' IR ' + (U '77E9 9635')
$tIrMask = 'IR ' + (U '5019 9009 6E29 5EA6 533A 57DF') + "`n" + (U '53EF 6620 5C04 56DE') + ' RGB ' + (U '56FE 50CF 6821 9A8C')
$tNext = (U '540E 7EED 98DF 6750 533A 57DF 8BC6 522B 4E0E 6E29 5EA6 8BA1 7B97 6A21 5757')
$tNote = (U '8BF4 660E') + ': RGB ' + (U '4E0E') + ' IR ' + (U '7531 96C6 6210 6A21 7EC4 91C7 96C6 FF0C 7ECF 65F6 95F4 540C 6B65 548C 7A7A 95F4 6807 5B9A 540E 5EFA 7ACB 5750 6807 5BF9 5E94 5173 7CFB FF0C 4E3A 98DF 6750 8868 9762 6E29 5EA6 8BA1 7B97 63D0 4F9B 6570 636E 57FA 7840 3002')

Draw-Box 610 60 580 90 $tModule

# Row 1: acquisition units and cooking scene
Draw-Box 85 245 430 95 $tRgbUnit $smallFont
Draw-Box 685 245 430 115 $tScene $smallFont $softFill
Draw-Box 1285 245 430 95 $tIrUnit $smallFont

# Split from integrated module to two collection units, with clear orthogonal lines.
$g.DrawLine($pen, 900, 150, 900, 195)
$g.DrawLine($pen, 300, 195, 1500, 195)
Draw-Arrow 300 195 300 245
Draw-Arrow 1500 195 1500 245

# Dashed observation relationship toward the cooking scene.
$g.DrawLine($dashPen, 515, 292, 685, 302)
$g.DrawLine($dashPen, 1285, 292, 1115, 302)

# Row 2: source data in two coordinate systems
Draw-Box 85 475 430 88 $tRgbCoord $smallFont
Draw-Box 1285 475 430 88 $tIrCoord $smallFont
Draw-Arrow 300 340 300 475
Draw-Arrow 1500 340 1500 475

# Row 3: synchronization and calibration, centered like Figure 1.
Draw-Box 585 660 630 95 $tSync $smallFont
Draw-PolylineArrow @(300,563,300,615,720,615,720,660)
Draw-PolylineArrow @(1500,563,1500,615,1080,615,1080,660)

Draw-Box 585 835 630 105 $tMap $smallFont
Draw-Arrow 900 755 900 835

# Row 4: bidirectional mapped candidate regions.
Draw-Box 85 1020 430 95 $tRgbMask $smallFont
Draw-Box 1285 1020 430 95 $tIrMask $smallFont
Draw-PolylineArrow @(760,940,760,980,300,980,300,1020)
Draw-PolylineArrow @(1040,940,1040,980,1500,980,1500,1020)

# Row 5: downstream module.
Draw-Box 610 1200 580 85 $tNext $smallFont
Draw-PolylineArrow @(515,1067,690,1067,690,1200)
Draw-PolylineArrow @(1285,1067,1110,1067,1110,1200)

$noteRect = New-Object System.Drawing.RectangleF(165, 1318, 1470, 38)
$sfNote = New-Object System.Drawing.StringFormat
$sfNote.Alignment = [System.Drawing.StringAlignment]::Center
$sfNote.LineAlignment = [System.Drawing.StringAlignment]::Center
$g.DrawString($tNote, $tinyFont, $brush, $noteRect, $sfNote)

$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)

$sfNote.Dispose()
$font.Dispose()
$smallFont.Dispose()
$tinyFont.Dispose()
$pen.Dispose()
$dashPen.Dispose()
$brush.Dispose()
$fill.Dispose()
$softFill.Dispose()
$g.Dispose()
$bmp.Dispose()

Get-Item -LiteralPath $out | Select-Object FullName, Length
