# Ollama 稳定性指南

> Session #46–48 — Ollama 假死问题 + qwythos-9b VL 废弃
>
> 适用环境：RTX 4060 8GB VRAM + Windows 11

## 问题描述

Ollama 进程在运行状态（任务管理器可见），但不再监听 11434 端口，所有 API 请求超时。现象：

- `ollama app.exe` 进程存在
- `llama-server.exe` 子进程存在但无响应
- `curl http://localhost:11434/api/tags` 超时
- VRAM 可能已被占满（通过 `nvidia-smi` 查看）

### 根因

| 触发条件 | 机制 |
|----------|------|
| 两模型并发加载 | qwythos-9b (6GB) + 任意模型 > 8GB → CUDA OOM → llama-server 死锁 |
| qwythos 大 context | 1M context window + 长 prompt → VRAM 碎片化 → 分配失败挂起 |
| 模型切换 (C3a→C3b) | 旧模型未完全卸载就加载新模型 → GPU 内存死锁 |
| 长时间 idle 后请求 | Windows 显卡驱动回收 VRAM → llama-server 访问非法地址 |

## 三层防护

### Layer 1: 环境变量（预防 — 消除 95% 假死场景）

在 Windows 系统环境变量中设置（需要**重启 Ollama** 生效）：

| 变量 | 值 | 作用 |
|------|-----|------|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | **关键**：绝不同时加载两个模型 |
| `OLLAMA_NUM_PARALLEL` | `1` | 单请求串行，防止并发 OOM |
| `OLLAMA_KEEP_ALIVE` | `5m` | 5 分钟无请求自动卸载，释放 VRAM |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | 限制 context window（VL 任务不需要 1M） |

设置方法（PowerShell 管理员）：

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_MAX_LOADED_MODELS', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_NUM_PARALLEL', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE', '5m', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', '32768', 'User')
```

设置后关闭并重新启动 Ollama 应用。

### Layer 2: 应用层预检 + 自动恢复（代码内）

`VLClient.ensure_ollama_ready()` — 位于 `_vl_client.py`：

```
每次 Ollama API 调用 →
  check_ollama_health() (cache 15s TTL) →
    OK → 继续
    FAIL → kill llama-server.exe (PowerShell)
         → 轮询 /api/ps (最长 30s)
         → 恢复成功 → 继续
         → 恢复失败 → RuntimeError + 手动恢复提示
```

集成点：
- `_call_ollama()` — 每次单图 VL 调用前自动预检
- `_call_ollama_multi()` — 每次多图 VL 调用前自动预检
- `safe_model_swap()` — C3a→C3b 切换时主动健康检查

对调用方的影响：
- Ollama 正常：零额外延迟（cache hit）
- Ollama 假死：自动尝试杀僵尸进程恢复，最长等待 30s
- 恢复失败：抛 `RuntimeError`，流水线自动回退到 regex fallback

### Layer 3: 外部看门狗脚本（独立进程监控）

`backend/scripts/ollama_watchdog.ps1` — 独立于 Python 进程的 PowerShell 监控：

```powershell
# 一次性健康检查（带自动恢复）
powershell.exe -NoProfile -File backend/scripts/ollama_watchdog.ps1 -Check

# 持续监控模式（后台运行，每 60s 检查一次）
powershell.exe -NoProfile -File backend/scripts/ollama_watchdog.ps1 -Watch

# 自定义检查间隔
powershell.exe -NoProfile -File backend/scripts/ollama_watchdog.ps1 -Watch -Interval 120
```

功能：
- 每 60s 探测 `/api/ps`
- 连续 2 次失败后触发自动恢复（避免瞬时网络波动误判）
- 杀死僵尸 `llama-server.exe`，等待 Ollama 自动重启后端
- 所有事件写入 `ollama_watchdog.log`
- 每小时输出统计摘要

## 手动恢复（兜底方案）

当自动恢复也失败时：

```powershell
# PowerShell（管理员）
Stop-Process -Name "llama-server" -Force
Stop-Process -Name "ollama" -Force
Start-Process "ollama app.exe"
# 等待 10s，然后验证：
curl http://localhost:11434/api/tags
```

## 架构约束

### 为什么不用 Docker 部署 Ollama？

Windows Docker 的 GPU 直通（`--gpus all`）需要 WSL2 + NVIDIA Container Toolkit，增加一层虚拟化开销。在 RTX 4060 8GB 上，宿主直接运行更稳定，VRAM 管理更可控。

### 模型选择策略

> **Session #48 更新**: qwythos-9b 从 VL 管线完全移除。C3b 使用 MIMO V2.5 唯一方案。

```
VL 任务（C3a 试卷结构化）:
  首选：MIMO V2.5 (cloud)
  本地：qwen2.5vl:3b (实际 VL VRAM ~6.2GB，仍可工作)

C3b LaTeX 公式提取:
  唯一：MIMO V2.5 (cloud)
  ❌ qwythos-9b VL 已移除 — 100% 崩溃率 (RemoteProtocolError @65s)
  ❌ qwen2.5vl:3b 不适合 — 公式检出率仅 13%

C4 配图检测:
  首选：MIMO V2.5 (cloud)
  本地：qwen2.5vl:3b

文本推理（题目批改）:
  首选：MIMO V2.5 (cloud)
  本地 fallback：vibethinker-3b:q8_0 (3.3GB)
  ❌ qwythos-9b：不再推荐 — 速度慢 (41.7s)，精度低 (33%)
```

## 相关文件

| 文件 | 内容 |
|------|------|
| `backend/app/domains/document/parallel_extraction/_vl_client.py` | `ensure_ollama_ready()`, `check_ollama_health()`, `unload_model()`, `safe_model_swap()` |
| `backend/scripts/ollama_watchdog.ps1` | 外部看门狗脚本 |
| `backend/.env` | `VL_PRIMARY=ollama` 配置 |
| `docker-compose.yml` | `OLLAMA_BASE_URL=http://host.docker.internal:11434` |

## 变更历史

| Session | 变更 |
|---------|------|
| #48 | qwythos-9b 从 VL 管线完全移除：config/.env/pipeline/C3/prompts/tests 全部清理；C3b 强制 MIMO |
| #47 | qwythos-9b VL 能力诊断：确认在 RTX 4060 8GB 上 100% 失败；更新模型选择策略，C3b 强制 MIMO |
| #46 | 环境变量 Layer 1 + `ensure_ollama_ready()` Layer 2 + 看门狗 Layer 3 |
| #34 | `safe_model_swap()` 含僵尸检测 |
| #27 | `unload_model()` 含 `/api/ps` 验证轮询 |
