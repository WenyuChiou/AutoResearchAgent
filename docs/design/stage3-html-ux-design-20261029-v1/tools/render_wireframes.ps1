# Draw static layout documents with Windows GDI. No browser or product UI is opened.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$artifactRoot=Split-Path -Parent $PSScriptRoot
$outputRoot=Join-Path $artifactRoot 'wireframes'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$fontCache=@{}
function Font([int]$size,[bool]$bold=$false) {
  $key="$size-$bold"
  if (-not $fontCache.ContainsKey($key)) { $fontCache[$key]=[Drawing.Font]::new('Microsoft YaHei',$size,$(if($bold){[Drawing.FontStyle]::Bold}else{[Drawing.FontStyle]::Regular}),[Drawing.GraphicsUnit]::Pixel) }
  return $fontCache[$key]
}
function Color([string]$value) { return [Drawing.ColorTranslator]::FromHtml($value) }
$measureBitmap=[Drawing.Bitmap]::new(1,1)
$measure=[Drawing.Graphics]::FromImage($measureBitmap)
$measure.TextRenderingHint=[Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$records=[Collections.Generic.List[object]]::new()
foreach($inputFile in Get-ChildItem -LiteralPath (Join-Path $artifactRoot 'blocks') -Filter '*.json') {
  $payload=Get-Content -LiteralPath $inputFile.FullName -Raw | ConvertFrom-Json
  foreach($canvasWidth in @(1440,390)) {
    $commands=[Collections.Generic.List[object]]::new()
    $bounds=[Collections.Generic.List[object]]::new()
    $margin=if($canvasWidth -eq 390){16}else{48}
    $inner=$canvasWidth-2*$margin
    function AddText([string]$value,[float]$x,[float]$y,[float]$width,[int]$size=17,[string]$color='#18334a',[bool]$bold=$false) {
      $height=[Math]::Ceiling($measure.MeasureString($value,(Font $size $bold),[int]$width).Height)+4
      $commands.Add([pscustomobject]@{kind='text';text=$value;x=$x;y=$y;w=$width;h=$height;size=$size;color=$color;bold=$bold})
      return $y+$height
    }
    function AddCard($block,[float]$x,[float]$y,[float]$width) {
      $start=$commands.Count; $pad=if($canvasWidth -eq 390){16}else{24}; $pos=$y+$pad
      $pos=AddText $block.title ($x+$pad) $pos ($width-2*$pad) 23 '#143f6b' $true
      $pos+=8
      foreach($paragraph in $block.paragraphs) { $pos=AddText ([string]$paragraph) ($x+$pad) $pos ($width-2*$pad) 16; $pos+=8 }
      if($block.id -eq 'figures' -and @($payload.explicit_edges).Count -gt 0) {
        $pos=AddText $payload.labels.field_graph_table_caption ($x+$pad) $pos ($width-2*$pad) 16 '#226b80' $true
        foreach($edge in $payload.explicit_edges) { $pos=AddText ($edge[0]+' → '+$edge[1]) ($x+$pad) $pos ($width-2*$pad) 15 }
      }
      $height=$pos-$y+$pad
      $commands.Insert($start,[pscustomobject]@{kind='rect';x=$x;y=$y;w=$width;h=$height;fill='#ffffff';stroke='#cad7e1'})
      $bounds.Add([pscustomobject]@{id=$block.id;x=$x;y=$y;w=$width;h=$height})
      return $y+$height+20
    }
    $y=28
    $y=AddText 'RESEARCH WORKSPACE · STATIC DESIGN v1' $margin $y $inner 16 '#226b80' $true
    $y+=16; $heroStart=$commands.Count; $heroY=$y; $pad=24
    $y=AddText $payload.labels.mock ($margin+$pad) ($y+$pad) ($inner-2*$pad) 15 '#ffffff'
    $y=AddText $payload.labels.title ($margin+$pad) ($y+10) ($inner-2*$pad) 16 '#ffffff'
    $y=AddText $payload.case.title ($margin+$pad) ($y+10) ($inner-2*$pad) $(if($canvasWidth -eq 390){27}else{34}) '#ffffff' $true
    $y=AddText ($payload.case.view_version+' · synthetic · baseline57ae0509') ($margin+$pad) ($y+8) ($inner-2*$pad) 14 '#ffffff'
    $y=AddText ($payload.labels.saved+' / '+$payload.labels.pending+' / '+$payload.labels.notrun) ($margin+$pad) ($y+10) ($inner-2*$pad) 15 '#ffffff'
    $y=AddText $payload.labels.boundary ($margin+$pad) ($y+10) ($inner-2*$pad) 15 '#ffffff'
    $buttonY=$y+14
    $buttonWidth=[Math]::Min(310,$inner-2*$pad)
    $commands.Add([pscustomobject]@{kind='rect';x=$margin+$pad;y=$buttonY;w=$buttonWidth;h=50;fill='#ffffff';stroke='#ffffff'})
    [void](AddText $payload.labels.primary ($margin+$pad+10) ($buttonY+10) ($buttonWidth-20) 16 '#143f6b' $true)
    $y=AddText $payload.labels.demo_actions ($margin+$pad) ($buttonY+62) ($inner-2*$pad) 14 '#ffffff'
    $heroHeight=$y-$heroY+$pad
    $commands.Insert($heroStart,[pscustomobject]@{kind='rect';x=$margin;y=$heroY;w=$inner;h=$heroHeight;fill='#143f6b';stroke='#143f6b'})
    $y=$heroY+$heroHeight+24
    foreach($b in $payload.blocks | Where-Object region -eq full) { $y=AddCard $b $margin $y $inner }
    if($canvasWidth -eq 390) {
      foreach($b in $payload.blocks | Where-Object region -ne full) { $y=AddCard $b $margin $y $inner }
    } else {
      $mainWidth=$inner-340-24; $mainY=$y; $sideY=$y
      foreach($b in $payload.blocks | Where-Object region -eq main) { $mainY=AddCard $b $margin $mainY $mainWidth }
      foreach($b in $payload.blocks | Where-Object region -eq side) { $sideY=AddCard $b ($margin+$mainWidth+24) $sideY 340 }
      $y=[Math]::Max($mainY,$sideY)
    }
    $y=AddText $payload.labels.field_wireframe_footer $margin ($y+10) $inner 14 '#405970'
    $fullHeight=[int]([Math]::Ceiling($y+32))
    foreach($b in $bounds) { if($b.x -lt 0 -or $b.x+$b.w -gt $canvasWidth -or $b.y -lt 0 -or $b.y+$b.h -gt $fullHeight) { throw 'Wireframe rectangle outside canvas' } }
    foreach($variant in @('full','viewport')) {
      $height=if($variant -eq 'viewport'){[Math]::Min($fullHeight,900)}else{$fullHeight}
      $bitmap=[Drawing.Bitmap]::new($canvasWidth,$height)
      $graphics=[Drawing.Graphics]::FromImage($bitmap)
      $graphics.Clear((Color '#f3f6f8')); $graphics.TextRenderingHint=[Drawing.Text.TextRenderingHint]::AntiAliasGridFit
      foreach($c in $commands) {
        if($c.kind -eq 'rect') {
          $brush=[Drawing.SolidBrush]::new((Color $c.fill)); $pen=[Drawing.Pen]::new((Color $c.stroke),1)
          $graphics.FillRectangle($brush,[single]$c.x,[single]$c.y,[single]$c.w,[single]$c.h);$graphics.DrawRectangle($pen,[single]$c.x,[single]$c.y,[single]$c.w,[single]$c.h)
          $brush.Dispose();$pen.Dispose()
        } else {
          $brush=[Drawing.SolidBrush]::new((Color $c.color));$rectangle=[Drawing.RectangleF]::new($c.x,$c.y,$c.w,$c.h)
          $graphics.DrawString($c.text,(Font $c.size $c.bold),$brush,$rectangle);$brush.Dispose()
        }
      }
      $filename=$payload.case.id+'.'+$payload.locale+'.'+$canvasWidth+'.'+$variant+'.png'
      $bitmap.Save((Join-Path $outputRoot $filename),[Drawing.Imaging.ImageFormat]::Png)
      $graphics.Dispose();$bitmap.Dispose()
      $records.Add([pscustomobject]@{file='wireframes/'+$filename;width=$canvasWidth;height=$height;variant=$variant;fixture_sha256=$payload.source_fixture_sha256;rectangle_count=$bounds.Count;canvas_bounds_checked=$true;browser_screenshot=$false})
    }
  }
}
foreach($f in $fontCache.Values){$f.Dispose()};$measure.Dispose();$measureBitmap.Dispose()
[IO.File]::WriteAllText((Join-Path $artifactRoot 'WIREFRAME_RENDER.json'),($records | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
[pscustomobject]@{images=$records.Count;renderer='Windows GDI';browser_UI_control='NOT_RUN'} | ConvertTo-Json -Compress
