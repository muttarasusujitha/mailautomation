param(
    [string]$Domain = 'sap trainer',
    [ValidateSet('trainer', 'client')][string]$Mode = 'trainer',
    [string]$Container = 'ts-intelligence-service',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$servicePath = Join-Path $PSScriptRoot '../services/intelligence-service'
$profileDirectory = [System.IO.Path]::GetFullPath((Join-Path $servicePath 'linkedin-bot-profile'))
$previousProfile = $env:LINKEDIN_BOT_PROFILE_PATH
Push-Location $servicePath
try {
    $env:LINKEDIN_BOT_PROFILE_PATH = $profileDirectory
    & $Python -u -m app.linkedin_authenticate --domain $Domain --mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Manual search verification did not complete. No session was transferred.' }

    # Send credentials over stdin only, into the existing private local volume.
    $installSession = 'import json,sys; from app.clients.linkedin_session import save_session; from app.clients.linkedin_browser import profile_path; save_session(profile_path(),json.load(sys.stdin))'
    Get-Content -Raw (Join-Path $profileDirectory 'linkedin-session.json') | docker exec -i $Container python -c $installSession
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the verified session in the local service.' }

    # The running image can be older than this checkout. Install the current
    # search modules and restart once so this run uses them.
    Write-Output 'Installing the current trainer search into the running service.'
    $modules = @(
        @{ Local = Join-Path $servicePath 'app/clients/linkedin_browser.py'; Probe = 'import app.clients.linkedin_browser as m; print(m.__file__)' },
        @{ Local = Join-Path $servicePath 'app/routes/linkedin_leads.py'; Probe = 'import app.routes.linkedin_leads as m; print(m.__file__)' }
    )
    foreach ($module in $modules) {
        $remote = (& docker exec $Container python -c $module.Probe)
        if ($LASTEXITCODE -ne 0 -or -not $remote) { throw 'Could not locate the search code inside the service.' }
        & docker cp $module.Local "${Container}:$($remote.Trim())"
        if ($LASTEXITCODE -ne 0) { throw 'Could not copy the trainer search into the service.' }
    }
    & docker restart $Container | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart the service after installing the trainer search.' }
    Write-Output 'Waiting for the service to finish restarting.'
    $probe = @'
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8005/health', timeout=3).read()
except Exception:
    sys.exit(1)
'@
    $serviceReady = $false
    $previousNative = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        foreach ($attempt in 1..30) {
            Start-Sleep -Seconds 2
            & docker exec $Container python -c $probe 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $serviceReady = $true; break }
        }
    } finally {
        $PSNativeCommandUseErrorActionPreference = $previousNative
    }
    if (-not $serviceReady) { throw 'The service did not become ready after the trainer search was installed.' }
    Write-Output 'Service is ready.'

    Write-Output 'Checking the actual application search once. No messages or emails are sent.'
    $checkSearch = @'
import httpx,json,sys
response=httpx.post('http://127.0.0.1:8005/api/v1/linkedin-leads/search',json={'domain':sys.argv[1],'mode':sys.argv[2],'search_provider':'linkedin_account','max_results':50,'save':True},timeout=300)
response.raise_for_status()
result=response.json()
print(json.dumps({key:result.get(key) for key in ['success','found','saved_count','skipped_count','search_error','auto_sent_count']}))
found = int(result.get('found') or 0)
saved = int(result.get('saved_count') or 0)
skipped = int(result.get('skipped_count') or 0)
if result.get('success') or found:
    print(f'APPLICATION_SEARCH_READY: Found {found}; saved {saved} new profile(s); {skipped} already saved.')
    sys.exit(0)
sys.exit(2)
'@
    & docker exec $Container python -c $checkSearch $Domain $Mode
    if ($LASTEXITCODE -ne 0) { throw 'The application search is not ready. Review the error above; this helper will not retry.' }
} finally {
    $env:LINKEDIN_BOT_PROFILE_PATH = $previousProfile
    Pop-Location
}
