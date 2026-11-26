 $project = "cinema-lab4-o44"
$worker = "$project-spark-worker-2-1"

$targetIP = (docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $worker).Trim()

if ($LASTEXITCODE -ne 0 -or -not $targetIP) {
    throw "Cannot identify Worker 2"
}

$prefix = $targetIP + ":"
$deadline = (Get-Date).AddMinutes(5)
$triggered = $false

Write-Host "WATCHER READY. Start Spark in the FIRST PowerShell."

while ((Get-Date) -lt $deadline) {
    try {
        $apps = Invoke-RestMethod "http://localhost:4040/api/v1/applications" -TimeoutSec 2
        $app = $apps | Where-Object { $_.name -eq "c01-lab4-o45-recovery" } | Select-Object -First 1

        if ($app) {
            $url = "http://localhost:4040/api/v1/applications/$($app.id)/executors"
            $executors = Invoke-RestMethod $url -TimeoutSec 2

            $worker2Busy = @($executors | Where-Object {
                $_.id -ne "driver" -and
                $_.hostPort.StartsWith($prefix) -and
                $_.activeTasks -gt 0
            })

            $worker1Busy = @($executors | Where-Object {
                $_.id -ne "driver" -and
                -not $_.hostPort.StartsWith($prefix) -and
                $_.activeTasks -gt 0
            })

            if ($worker2Busy.Count -gt 0 -and $worker1Busy.Count -gt 0) {
                $triggered = $true
                break
            }
        }
    }
    catch {
        Write-Host "Spark API: $($_.Exception.Message)"
    }

    Start-Sleep -Milliseconds 500
}

if ($triggered) {
    Write-Host "BOTH WORKERS BUSY. Stopping Worker 2..."
    docker compose -p $project stop spark-worker-2
}
else {
    Write-Host "No simultaneous active tasks detected. Worker 2 was NOT stopped."
}