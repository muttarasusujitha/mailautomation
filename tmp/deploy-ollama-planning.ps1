$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\sujit\Desktop\mail'
$repo = Join-Path $workspace 'mailautomation\microservices'
$backup = Join-Path $workspace ('tmp\ollama-planning-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$files = @(
    @{ Container = 'ts-trainer-service'; Source = 'services/trainer-service/app/ollama_curriculum.py'; Target = '/app/app/ollama_curriculum.py' },
    @{ Container = 'ts-trainer-service'; Source = 'services/trainer-service/app/ollama_client.py'; Target = '/app/app/ollama_client.py' },
    @{ Container = 'ts-trainer-service'; Source = 'services/trainer-service/app/toc_evaluation.py'; Target = '/app/app/toc_evaluation.py' },
    @{ Container = 'ts-trainer-service'; Source = 'services/trainer-service/app/routes/toc_extended.py'; Target = '/app/app/routes/toc_extended.py' },
    @{ Container = 'ts-trainer-service'; Source = 'shared/lab_planning.py'; Target = '/app/shared/lab_planning.py' },
    @{ Container = 'ts-document-service'; Source = 'shared/lab_planning.py'; Target = '/app/shared/lab_planning.py' }
)
function Invoke-DockerChecked([string[]] $DockerArguments) {
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($DockerArguments[0])" }
}
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($file in $files) {
    $file.Backup = Join-Path $backup ($file.Container + '-' + $file.Target.Replace('/', '_'))
    Invoke-DockerChecked @('cp', ($file.Container + ':' + $file.Target), $file.Backup)
    $file.Hash = (Get-FileHash -LiteralPath (Join-Path $repo $file.Source) -Algorithm SHA256).Hash.ToLower()
}
$files | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
try {
    foreach ($file in $files) {
        Invoke-DockerChecked @('cp', (Join-Path $repo $file.Source), ($file.Container + ':' + $file.Target))
        $actual = & docker exec $file.Container sha256sum $file.Target
        if ($LASTEXITCODE -ne 0 -or -not $actual.StartsWith($file.Hash)) { throw "Hash mismatch: $($file.Target)" }
    }
    Invoke-DockerChecked @('exec', 'ts-trainer-service', 'python', '-c', "from app.ollama_curriculum import ClientCurriculum; from app.routes import toc_extended; from shared.lab_planning import plan_resources; print('Trainer imports passed')")
    Invoke-DockerChecked @('exec', 'ts-document-service', 'python', '-c', "from shared.lab_planning import plan_resources; print('Document imports passed')")
    Invoke-DockerChecked @('restart', 'ts-trainer-service', 'ts-document-service')
    foreach ($container in @('ts-trainer-service', 'ts-document-service')) {
        $healthy = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $state = & docker inspect --format '{{.State.Health.Status}}' $container
            if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $container" }
            if ($state -eq 'healthy') { $healthy = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $healthy) { throw "$container did not become healthy" }
        Write-Output "$container is healthy"
    }
    Write-Output "Updated local services. Backup: $backup"
} catch {
    $failure = $_
    Write-Warning 'Deployment failed; restoring original files.'
    foreach ($file in $files) {
        Invoke-DockerChecked @('cp', $file.Backup, ($file.Container + ':' + $file.Target))
    }
    Invoke-DockerChecked @('restart', 'ts-trainer-service', 'ts-document-service')
    throw $failure
}
