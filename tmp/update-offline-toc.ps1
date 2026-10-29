$ErrorActionPreference = 'Stop'
$root = 'C:\Users\sujit\Desktop\mail\mailautomation'
$backup = 'C:\Users\sujit\Desktop\mail\tmp\offline-toc-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $backup | Out-Null
function Run-Docker([string[]] $Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($Arguments[0])" }
}
foreach ($container in @('ts-trainer-service', 'ts-document-service', 'mailautomation-frontend-1')) {
    $destination = Join-Path $backup $container
    New-Item -ItemType Directory -Path $destination | Out-Null
    $source = if ($container -eq 'mailautomation-frontend-1') { '/app/src/pages' } else { '/app/app' }
    Run-Docker @('cp', "${container}:$source", $destination)
}
foreach ($file in @('reference_planner.py', 'offline_programme.py', 'routes/toc.py')) {
    Run-Docker @('cp', "$root/microservices/services/trainer-service/app/$file", "ts-trainer-service:/app/app/$file")
}
foreach ($file in @('toc_reference_excel.py', 'routes/excel.py')) {
    Run-Docker @('cp', "$root/microservices/services/document-service/app/$file", "ts-document-service:/app/app/$file")
}
foreach ($file in @('Shortlist.jsx', 'Shortlist1.jsx')) {
    Run-Docker @('cp', "$root/frontend/src/pages/$file", "mailautomation-frontend-1:/app/src/pages/$file")
}
Run-Docker @('exec', 'ts-trainer-service', 'python', '-m', 'compileall', '-q', '/app/app')
Run-Docker @('exec', 'ts-document-service', 'python', '-m', 'compileall', '-q', '/app/app')
Run-Docker @('restart', 'ts-trainer-service', 'ts-document-service')
Write-Output "Local TOC fixes loaded. Backup: $backup"
