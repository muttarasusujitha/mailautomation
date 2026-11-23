<#
Starts the LinkedIn bot sign-in on this PC, using its own local browser profile.
Run this file from Windows Explorer or a normal PowerShell window, then complete
LinkedIn sign-in in the browser window that opens.
#>
[CmdletBinding()]
param(
    [string]$Domain = 'Python',
    [ValidateSet('trainer', 'client')][string]$Mode = 'trainer'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSCommandPath
$service = Join-Path $root 'microservices/services/intelligence-service'
$python = Join-Path $root '.venv/Scripts/python.exe'
$profile = Join-Path $service 'linkedin-local-bot-profile'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}

# Stop only abandoned browsers started by this project's Playwright runtime.
Get-Process chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*ms-playwright\chromium-1187\chrome-win\chrome.exe' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

$env:PYTHONPATH = Join-Path $root 'microservices'
$env:LINKEDIN_BOT_PROFILE_PATH = $profile
Set-Location -LiteralPath $service

Write-Host 'Opening the local LinkedIn bot browser...'
Write-Host 'Complete sign-in or account verification in that window. Do not enter credentials in chat.'
& $python -u -m app.linkedin_authenticate --domain $Domain --mode $Mode
if ($LASTEXITCODE -ne 0) {
    throw 'LinkedIn sign-in or search verification did not complete.'
}

Write-Host 'Local LinkedIn bot session is ready.'
