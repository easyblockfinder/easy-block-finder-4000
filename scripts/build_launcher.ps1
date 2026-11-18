# Compile EBF4000.exe GUI launcher (no console) with .NET Framework csc.
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = $Root }

$src = Join-Path $PSScriptRoot "launcher\EBF4000Launcher.cs"
$out = Join-Path $OutDir "EBF4000.exe"
$pngIcon = Join-Path $Root "assets\ebf4000_icon.png"
$icoIcon = Join-Path $Root "assets\ebf4000_icon.ico"

$csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework64\v4*\csc.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $csc) {
    $csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework\v4*\csc.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
}
if (-not $csc) { throw "csc.exe not found (need .NET Framework 4.x)" }

function New-Win32IconFromPng {
    <#
    Writes a classic multi-size Win32 ICO (BMP DIB entries) that csc /win32icon accepts.
    System.Drawing.Icon.Save(GetHicon()) produces a non-standard stream csc rejects.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$PngPath,
        [Parameter(Mandatory = $true)][string]$IcoPath,
        [int[]]$Sizes = @(16, 32, 48, 256)
    )
    Add-Type -AssemblyName System.Drawing

    $src = [System.Drawing.Bitmap]::FromFile($PngPath)
    try {
        $images = New-Object System.Collections.Generic.List[byte[]]
        foreach ($size in $Sizes) {
            $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
            try {
                $g = [System.Drawing.Graphics]::FromImage($bmp)
                try {
                    $g.Clear([System.Drawing.Color]::Transparent)
                    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
                    $g.DrawImage($src, 0, 0, $size, $size)
                } finally {
                    $g.Dispose()
                }

                $rect = New-Object System.Drawing.Rectangle 0, 0, $size, $size
                $data = $bmp.LockBits(
                    $rect,
                    [System.Drawing.Imaging.ImageLockMode]::ReadOnly,
                    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
                try {
                    $stride = $data.Stride
                    $px = New-Object byte[] ($stride * $size)
                    [Runtime.InteropServices.Marshal]::Copy($data.Scan0, $px, 0, $px.Length)

                    # XOR bitmap: bottom-up BGRA (ARGB bytes already BGRA in memory for 32bppArgb)
                    $xor = New-Object byte[] ($size * $size * 4)
                    for ($y = 0; $y -lt $size; $y++) {
                        $srcRow = $y * $stride
                        $dstRow = ($size - 1 - $y) * $size * 4
                        [Buffer]::BlockCopy($px, $srcRow, $xor, $dstRow, $size * 4)
                    }

                    # 1bpp AND mask, rows padded to 4 bytes, bottom-up; 0 = opaque
                    $andRowBytes = [Math]::Ceiling($size / 32.0) * 4
                    $and = New-Object byte[] ($andRowBytes * $size)

                    $bih = New-Object byte[] 40
                    [BitConverter]::GetBytes([int32]40).CopyTo($bih, 0)           # biSize
                    [BitConverter]::GetBytes([int32]$size).CopyTo($bih, 4)        # biWidth
                    [BitConverter]::GetBytes([int32]($size * 2)).CopyTo($bih, 8)  # biHeight = height*2 (XOR+AND)
                    [BitConverter]::GetBytes([int16]1).CopyTo($bih, 12)           # biPlanes
                    [BitConverter]::GetBytes([int16]32).CopyTo($bih, 14)          # biBitCount
                    [BitConverter]::GetBytes([int32]0).CopyTo($bih, 16)           # biCompression = BI_RGB
                    [BitConverter]::GetBytes([int32]$xor.Length).CopyTo($bih, 20) # biSizeImage

                    $img = New-Object byte[] ($bih.Length + $xor.Length + $and.Length)
                    [Buffer]::BlockCopy($bih, 0, $img, 0, $bih.Length)
                    [Buffer]::BlockCopy($xor, 0, $img, $bih.Length, $xor.Length)
                    [Buffer]::BlockCopy($and, 0, $img, $bih.Length + $xor.Length, $and.Length)
                    $images.Add($img) | Out-Null
                } finally {
                    $bmp.UnlockBits($data)
                }
            } finally {
                $bmp.Dispose()
            }
        }

        $count = $images.Count
        $offset = 6 + (16 * $count)
        $ms = New-Object System.IO.MemoryStream
        $bw = New-Object System.IO.BinaryWriter $ms
        try {
            $bw.Write([uint16]0)      # reserved
            $bw.Write([uint16]1)      # type = icon
            $bw.Write([uint16]$count)
            for ($i = 0; $i -lt $count; $i++) {
                $sz = $Sizes[$i]
                $wByte = if ($sz -ge 256) { [byte]0 } else { [byte]$sz }
                $hByte = if ($sz -ge 256) { [byte]0 } else { [byte]$sz }
                $bw.Write($wByte)
                $bw.Write($hByte)
                $bw.Write([byte]0)    # color count
                $bw.Write([byte]0)    # reserved
                $bw.Write([uint16]1)  # planes
                $bw.Write([uint16]32) # bit count
                $bw.Write([uint32]$images[$i].Length)
                $bw.Write([uint32]$offset)
                $offset += $images[$i].Length
            }
            foreach ($img in $images) { $bw.Write($img) }
            $bw.Flush()
            [IO.File]::WriteAllBytes($IcoPath, $ms.ToArray())
        } finally {
            $bw.Dispose()
            $ms.Dispose()
        }
    } finally {
        $src.Dispose()
    }
}

# Always regenerate a csc-compatible ICO from PNG when source art exists.
if (Test-Path -LiteralPath $pngIcon) {
    Write-Host "Generating Win32 ICO: $icoIcon"
    New-Win32IconFromPng -PngPath $pngIcon -IcoPath $icoIcon
} elseif (-not (Test-Path -LiteralPath $icoIcon)) {
    Write-Warning "No assets\ebf4000_icon.png (or .ico); compiling without /win32icon"
}

$cscArgs = @(
    "/nologo", "/target:winexe", "/optimize+",
    "/r:System.Windows.Forms.dll", "/r:System.dll",
    "/out:$out"
)
if (Test-Path -LiteralPath $icoIcon) {
    $cscArgs += "/win32icon:$icoIcon"
    Write-Host "Embedding icon: $icoIcon"
}
$cscArgs += $src

Write-Host "Compiling $out with $($csc.FullName)"
& $csc.FullName @cscArgs
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
if (-not (Test-Path -LiteralPath $out)) { throw "EBF4000.exe not produced" }
Write-Host "OK: $out ($([math]::Round((Get-Item $out).Length/1KB,1)) KB)"
exit 0
