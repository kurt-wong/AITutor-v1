# start.ps1 — 启动后端（推荐使用 --supervised 模式获得自动重启）
# 用法:
#   .\start.ps1                  → 普通模式（崩溃后需手动重启）
#   .\start.ps1 -Supervised      → 看门狗模式（崩溃自动重启，推荐）
#   .\start.ps1 -Reload          → 开发模式（--reload，不稳定，不推荐）

param(
    [switch]$Supervised,
    [switch]$Reload
)

$port = 8000

# 查找并杀掉占用端口的进程（快速清理，start_backend.py 会再做一次完整清理）
$connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($connections) {
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[start.ps1] Killing $($proc.ProcessName) (PID $pid) on port $port" -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
}

# 构建启动命令
$cmd = "python scripts/start_backend.py --port $port"
if ($Supervised) {
    $cmd += " --supervised"
    Write-Host "[start.ps1] SUPERVISED mode — auto-restart on crash" -ForegroundColor Green
} elseif ($Reload) {
    $cmd += " --reload"
    Write-Host "[start.ps1] RELOAD mode — WARNING: unstable" -ForegroundColor Yellow
} else {
    Write-Host "[start.ps1] One-shot mode — use -Supervised for auto-restart" -ForegroundColor Cyan
}

Write-Host "[start.ps1] Running: $cmd" -ForegroundColor Cyan
Invoke-Expression $cmd
