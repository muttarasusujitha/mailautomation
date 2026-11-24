$ErrorActionPreference = 'Stop'
$root = 'C:\Users\sujit\Desktop\mail\mailautomation\microservices'
$backup = 'C:\Users\sujit\Desktop\mail\tmp\module-lab-cost-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $backup | Out-Null
function Run-Docker([string[]] $Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($Arguments[0])" }
}
foreach ($container in @('ts-trainer-service', 'ts-document-service')) {
    $destination = Join-Path $backup $container
    New-Item -ItemType Directory -Path $destination | Out-Null
    Run-Docker @('cp', "${container}:/app/app", $destination)
    Run-Docker @('cp', "${container}:/app/shared", $destination)
    foreach ($file in @('lab_curriculum.py', 'lab_planning.py', 'lab_cost_inputs.py')) {
        Run-Docker @('cp', "$root/shared/$file", "${container}:/app/shared/$file")
    }
}
Run-Docker @('cp', "$root/services/trainer-service/app/routes/toc.py", 'ts-trainer-service:/app/app/routes/toc.py')
foreach ($file in @('lab_plan.py', 'routes/excel.py')) {
    Run-Docker @('cp', "$root/services/document-service/app/$file", "ts-document-service:/app/app/$file")
}
foreach ($container in @('ts-trainer-service', 'ts-document-service')) {
    Run-Docker @('exec', $container, 'python', '-m', 'compileall', '-q', '/app/app', '/app/shared')
}
Run-Docker @('restart', 'ts-trainer-service', 'ts-document-service')
Write-Output "Module lab costing activated; backup: $backup"
