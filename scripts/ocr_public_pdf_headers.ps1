param(
    [Parameter(Mandatory=$true)][string]$ImageDirectory,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
# Recognize local rendered public metadata headers only. No app/window access.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$ocrTaskAdapter = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-OcrOperation($Operation, [type]$ResultType) {
    $ocrTask = $ocrTaskAdapter.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $ocrTask.Wait(30000)) { throw 'Local OCR operation exceeded 30 seconds.' }
    return $ocrTask.Result
}
$ocrLanguage = [Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime]::new('en-US')
$ocrEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($ocrLanguage)
if (-not $ocrEngine) { throw 'The local English OCR recognizer is unavailable.' }
$ocrInputPath = (Resolve-Path -LiteralPath $ImageDirectory).Path
if (Test-Path -LiteralPath $OutputDirectory) { throw 'The output directory must be new.' }
$ocrOutputPath = (New-Item -ItemType Directory -Path $OutputDirectory).FullName
$ocrManifest = [ordered]@{
    created_at_utc = [DateTime]::UtcNow.ToString('o')
    input_directory = $ocrInputPath
    engine = 'Windows.Media.Ocr.OcrEngine'
    language = $ocrEngine.RecognizerLanguage.LanguageTag
    powershell_version = $PSVersionTable.PSVersion.ToString()
    os_version = [Environment]::OSVersion.Version.ToString()
    reading_scope = 'local_public_PDF_header_images_only'
    article_database_writes = 0
    ocr_outputs_are_candidates = $true
}
[IO.File]::WriteAllText((Join-Path $ocrOutputPath 'manifest.json'),
    ($ocrManifest | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
foreach ($ocrImage in Get-ChildItem -LiteralPath $ocrInputPath -Filter '*.png') {
    $ocrFile = Wait-OcrOperation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ocrImage.FullName)) ([Windows.Storage.StorageFile])
    $ocrStream = Wait-OcrOperation ($ocrFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $ocrBitmap = $null
    try {
        $ocrDecoder = Wait-OcrOperation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ocrStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $ocrBitmap = Wait-OcrOperation ($ocrDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocrResult = Wait-OcrOperation ($ocrEngine.RecognizeAsync($ocrBitmap)) ([Windows.Media.Ocr.OcrResult])
        $ocrDetails = [ordered]@{image_path=$ocrImage.FullName;image_sha256=(Get-FileHash -LiteralPath $ocrImage.FullName -Algorithm SHA256).Hash.ToLower();text=$ocrResult.Text;
            lines=@($ocrResult.Lines | ForEach-Object { $_.Text });engine='Windows.Media.Ocr';language='en-US';status='OCR_CANDIDATE';article_database_writes=0}
        [IO.File]::WriteAllText((Join-Path $ocrOutputPath ($ocrImage.BaseName+'.json')),
            ($ocrDetails | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
        Write-Output ($ocrImage.BaseName + ' OCR_CANDIDATE')
    } finally {
        if ($ocrBitmap) { $ocrBitmap.Dispose() }
        $ocrStream.Dispose()
    }
}
