param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Wait-WinRt {
    param(
        [object]$Operation,
        [Type]$ResultType
    )
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Length -eq 1 -and $_.GetParameters().Length -eq 1
        } | Select-Object -First 1
    if (-not $method) { throw 'Windows Runtime async bridge is unavailable.' }
    $closedMethod = $method.MakeGenericMethod([type[]]@($ResultType))
    $task = $closedMethod.Invoke($null, [object[]]@($Operation))
    $task.Wait()
    return $task.GetAwaiter().GetResult()
}

$ocrType = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$fileType = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$accessType = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$streamType = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage, ContentType=WindowsRuntime]
$decoderType = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$bitmapType = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$resultType = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$engine = $ocrType::TryCreateFromUserProfileLanguages()
if (-not $engine) { throw 'No Windows OCR language is installed for the current user.' }
$file = Wait-WinRt ($fileType::GetFileFromPathAsync((Resolve-Path -LiteralPath $ImagePath).Path)) $fileType
$stream = Wait-WinRt ($file.OpenAsync($accessType::Read)) $streamType
$decoder = Wait-WinRt ($decoderType::CreateAsync($stream)) $decoderType
$bitmap = Wait-WinRt ($decoder.GetSoftwareBitmapAsync()) $bitmapType
$result = Wait-WinRt ($engine.RecognizeAsync($bitmap)) $resultType
$ocrLines = foreach ($line in $result.Lines) {
    $left = [double]::PositiveInfinity
    $top = [double]::PositiveInfinity
    $right = 0.0
    $bottom = 0.0
    foreach ($word in $line.Words) {
        $rect = $word.BoundingRect
        $left = [Math]::Min($left, [double]$rect.X)
        $top = [Math]::Min($top, [double]$rect.Y)
        $right = [Math]::Max($right, [double]$rect.X + [double]$rect.Width)
        $bottom = [Math]::Max($bottom, [double]$rect.Y + [double]$rect.Height)
    }
    [pscustomobject]@{
        text = [string]$line.Text
        x = $left
        y = $top
        width = $right - $left
        height = $bottom - $top
        image_width = [double]$decoder.PixelWidth
    }
}
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($ocrLines) -Compress))
