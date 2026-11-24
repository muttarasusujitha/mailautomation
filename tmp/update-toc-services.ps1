$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\sujit\Desktop\mail\mailautomation\microservices'
$backup = 'C:\Users\sujit\Desktop\mail\tmp\toc-services-backup-20260922'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
function Invoke-DockerChecked([string[]] $DockerArguments) {
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($DockerArguments[0])" }
}
foreach ($service in @('trainer', 'document')) {
    $container = "ts-$service-service"
    $destination = Join-Path $backup $service
    if (Test-Path -LiteralPath $destination) { throw "Backup already exists: $destination" }
    New-Item -ItemType Directory -Path $destination | Out-Null
    Invoke-DockerChecked @('cp', "${container}:/app/app", $destination)
    Invoke-DockerChecked @('cp', "${container}:/app/shared", $destination)
}
$trainerFiles = @('curriculum_reasoning.py', 'reference_planner.py', 'routes/toc.py', 'routes/toc_extended.py')
foreach ($relative in $trainerFiles) {
    Invoke-DockerChecked @('cp', "$repo/services/trainer-service/app/$relative", "ts-trainer-service:/app/app/$relative")
}
Invoke-DockerChecked @('cp', "$repo/services/trainer-service/app/reference_curricula", 'ts-trainer-service:/app/app/reference_curricula')
foreach ($relative in @('toc_reference_excel.py', 'routes/excel.py')) {
    Invoke-DockerChecked @('cp', "$repo/services/document-service/app/$relative", "ts-document-service:/app/app/$relative")
}
foreach ($container in @('ts-trainer-service', 'ts-document-service')) {
    Invoke-DockerChecked @('cp', "$repo/shared/toc_layouts.py", "${container}:/app/shared/toc_layouts.py")
    Invoke-DockerChecked @('exec', $container, 'python', '-m', 'compileall', '-q', '/app/app', '/app/shared/toc_layouts.py')
}
Invoke-DockerChecked @('restart', 'ts-trainer-service', 'ts-document-service')
Write-Output "TOC services updated. Backup: $backup"
