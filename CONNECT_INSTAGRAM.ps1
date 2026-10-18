param([string]$ProjectRoot = "$HOME\Desktop\instagram-shop-importer")
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing project Python: $python"
}
Push-Location $ProjectRoot
try {
    Write-Host 'Close Selora Importer before connecting Instagram.' -ForegroundColor Yellow
    Write-Host 'Sign in ONLY on the official instagram.com page in the new Chrome window.'
    & $python -m app.crawler.instagram.connect_session
    if ($LASTEXITCODE -ne 0) {
        throw 'Instagram was not connected; previous session is unchanged.'
    }
} finally {
    Pop-Location
}
