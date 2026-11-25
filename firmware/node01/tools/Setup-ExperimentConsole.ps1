param(
    [string]$VenvDirectory='C:\Users\LQY\Documents\Codex\node01-pc-console-venv',
    [string]$BasePython='C:\Users\LQY\Documents\Codex\esp55\tools\python_env\idf5.5_py3.12_env\Scripts\python.exe'
)
$ErrorActionPreference='Stop'
$nodeSdkEnvironment='C:\Users\LQY\Documents\Codex\esp55\tools\python_env'
$nodeVenv=[System.IO.Path]::GetFullPath($VenvDirectory)
if ($nodeVenv.StartsWith($nodeSdkEnvironment,[System.StringComparison]::OrdinalIgnoreCase)) { throw '拒绝将PC依赖装入ESP-IDF固定环境' }
$nodeMarker=Join-Path $nodeVenv '.node01_pc_console_env'
if (Test-Path -LiteralPath $nodeVenv) {
    if (-not (Test-Path -LiteralPath $nodeMarker -PathType Leaf)) { throw '现有目录不是已标记的NODE-01 PC环境；请选全新-VenvDirectory，禁止覆盖其它环境' }
} else {
    if (-not (Test-Path -LiteralPath $BasePython -PathType Leaf)) { throw '基础Python不存在' }
    & $BasePython -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw '需要Python3.11+' }
    & $BasePython -m venv $nodeVenv
    if ($LASTEXITCODE -ne 0) { throw '独立venv创建失败' }
    'NODE01_PC_CONSOLE_ONLY; never ESP-IDF environment' | Set-Content -LiteralPath $nodeMarker -Encoding UTF8
}
$nodePython=Join-Path $nodeVenv 'Scripts\python.exe'
& $nodePython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'experiment_console\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'PC依赖安装失败，未写SDK环境' }
& $nodePython -c 'import sys,serial,prompt_toolkit,tzdata; print(sys.executable); print("pyserial",serial.__version__,"prompt_toolkit",prompt_toolkit.__version__,"tzdata",tzdata.__version__)'
if ($LASTEXITCODE -ne 0) { throw '依赖import核验失败' }
