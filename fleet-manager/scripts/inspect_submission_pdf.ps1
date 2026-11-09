param(
    [string]$PdfPath = (Join-Path $PSScriptRoot '..\submission\final\Adarsh_Singh_SWFW_5S_12.pdf'),
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument,Windows.Data.Pdf,ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null = [Windows.Data.Pdf.PdfPageRenderOptions,Windows.Data.Pdf,ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
$asActionTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
} | Select-Object -First 1
function Await-Operation($Operation, [Type]$ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($PdfPath))) ([Windows.Storage.StorageFile])
$document = Await-Operation ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
$pages = @()
for($i=0; $i -lt $document.PageCount; $i++) {
    $page = $document.GetPage($i)
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $options.DestinationWidth = 1000
    $action = $page.RenderToStreamAsync($stream, $options)
    $task = $asActionTask.Invoke($null, @($action))
    $task.Wait()
    $stream.Seek(0)
    $inputStream = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
    $path = Join-Path $OutputDirectory ('page-{0:D3}.png' -f ($i+1))
    $out = [IO.File]::Create($path)
    $inputStream.CopyTo($out)
    $out.Dispose(); $inputStream.Dispose(); $stream.Dispose(); $page.Dispose()
    $pages += $path
}
# Contact sheets retain all page boundaries; individual PNGs permit legibility checks.
for($start=0; $start -lt $pages.Count; $start+=12) {
    $count = [Math]::Min(12, $pages.Count-$start)
    $rows = [int][Math]::Ceiling($count/3.0)
    $sheet = New-Object Drawing.Bitmap(900, ($rows*450))
    $graphics = [Drawing.Graphics]::FromImage($sheet)
    $graphics.Clear([Drawing.Color]::LightGray)
    for($j=0; $j -lt $count; $j++) {
        $image = [Drawing.Image]::FromFile($pages[$start+$j])
        $graphics.DrawImage($image, (($j%3)*300+5), ([int][Math]::Floor($j/3.0)*450+5), 290, 410)
        $graphics.DrawString(('Page '+($start+$j+1)), (New-Object Drawing.Font('Arial',10)), [Drawing.Brushes]::Black, (($j%3)*300+8), ([int][Math]::Floor($j/3.0)*450+420))
        $image.Dispose()
    }
    $sheet.Save((Join-Path $OutputDirectory ('contact-{0:D3}.png' -f ($start+1))), [Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $sheet.Dispose()
}
@{pages=$document.PageCount; rendered=$pages.Count; pdf=[IO.Path]::GetFullPath($PdfPath); renderer='Windows.Data.Pdf'; timestamp_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'pdf-inspection.json') -Encoding UTF8
Write-Output "Rendered $($pages.Count) PDF pages to $OutputDirectory"