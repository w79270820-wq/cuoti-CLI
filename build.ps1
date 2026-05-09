# build.ps1 — 错题本打包脚本（PowerShell 版）
# 用法: .\build.ps1
# 如遇执行策略限制，先运行: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "错题本 打包中..."

function Write-Step($n, $msg) {
    Write-Host "[$n/4] $msg" -ForegroundColor Cyan
}
function Write-OK($msg) {
    Write-Host "  ✓ $msg" -ForegroundColor Green
}
function Write-Fail($msg) {
    Write-Host "[错误] $msg" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Clear-Host
Write-Host "================================================" -ForegroundColor Yellow
Write-Host "  错题本 打包脚本  cuoti v3.0" -ForegroundColor Yellow
Write-Host "  生成 dist\错题本.exe" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Yellow
Write-Host ""

# ── 1. 检查 Python ─────────────────────────────────────────────────────────
Write-Step 1 "检查 Python 环境..."
try {
    $ver = python --version 2>&1
    Write-OK "Python 已找到: $ver"
} catch {
    Write-Fail "未找到 Python，请先安装: https://www.python.org/downloads/"
}

# ── 2. 安装 PyInstaller ─────────────────────────────────────────────────────
Write-Step 2 "安装 / 更新 PyInstaller..."
python -m pip install pyinstaller --quiet --upgrade
if ($LASTEXITCODE -ne 0) { Write-Fail "PyInstaller 安装失败，请检查网络" }
Write-OK "PyInstaller 就绪"

# ── 3. 检查必要文件 ─────────────────────────────────────────────────────────
Write-Step 3 "检查项目文件..."
if (-not (Test-Path "app.py"))          { Write-Fail "找不到 app.py，请在项目根目录运行" }
if (-not (Test-Path "ui\index.html"))   { Write-Fail "找不到 ui\index.html" }
if (-not (Test-Path "cuoti.spec"))      { Write-Fail "找不到 cuoti.spec" }
Write-OK "文件检查通过"

# ── 4. 打包 ────────────────────────────────────────────────────────────────
Write-Step 4 "开始打包，约 30~60 秒..."
Write-Host ""

python -m PyInstaller cuoti.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Fail "打包失败，请查看上方错误信息" }

# ── 完成 ──────────────────────────────────────────────────────────────────
$exePath = Resolve-Path "dist\cuoti.exe"
$exeSize = [math]::Round((Get-Item $exePath).Length / 1MB, 1)

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  打包成功！" -ForegroundColor Green
Write-Host ""
Write-Host "  exe 路径: $exePath" -ForegroundColor White
Write-Host "  文件大小: ${exeSize} MB" -ForegroundColor White
Write-Host ""
Write-Host "  数据库将在首次运行时生成于 exe 同目录" -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Green
Write-Host ""

$run = Read-Host "立即运行测试? (y/n)"
if ($run -eq "y" -or $run -eq "Y") {
  Start-Process $exePath
}
