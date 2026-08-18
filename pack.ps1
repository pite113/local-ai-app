# 一键打包交付包脚本
# 用法: 双击"一键打包.bat" 或运行  powershell -ExecutionPolicy Bypass -File pack.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format 'yyyyMMdd_HHmm'
$outDir = Join-Path $root '交付包'
$stage = Join-Path $outDir "local-ai-app_$stamp"
$zip   = Join-Path $outDir "local-ai-app_$stamp.zip"

Write-Host ""
Write-Host "========== 开始打包 =========="

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 白名单：只拷贝交付需要的文件（绝不包含 .env / .venv / data / .git）
$items = @(
    'app', 'run.py', 'start.bat',
    '启动服务.bat', '停止服务.bat',
    'requirements.txt', 'README.md', 'DEPLOY.md',
    '.env.example', '.gitignore'
)
foreach ($it in $items) {
    $src = Join-Path $root $it
    if (Test-Path $src) {
        Copy-Item $src $stage -Recurse -Force
        Write-Host "  ✓ $it"
    } else {
        Write-Host "  ⚠ 缺失(忽略): $it"
    }
}

# 清理打包目录里的缓存
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 打 zip（整目录打包，确保包含 .env.example 等隐藏文件）
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host ""
Write-Host "========== 打包完成 =========="
Write-Host "交付包: $zip"
Write-Host "大小  : $sizeMB MB"
Write-Host "--------------------------------"
Write-Host "[安全] 已排除: .env(密钥) .venv(环境) data(数据) .git(历史)"
Write-Host "[客户] 使用: 装Python -> 解压 -> 复制 .env.example 为 .env 填密钥 -> 双击 start.bat"
Write-Host ""
