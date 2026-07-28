# start.ps1 — 启动后端前清理端口 8000 上的残留进程
# 解决 Windows uvicorn --reload 僵尸进程问题 (Session #137)

$port = 8000

# 查找并杀掉占用端口的进程
$connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($connections) {
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Killing process $($proc.ProcessName) (PID $pid) on port $port" -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
    Write-Host "Port $port cleared." -ForegroundColor Green
} else {
    Write-Host "Port $port is free." -ForegroundColor Green
}

# 启动 uvicorn
Write-Host "Starting uvicorn..." -ForegroundColor Cyan
python -m uvicorn app.main:app --host 0.0.0.0 --port $port --reload
