param(
    [string]$Port='COM7', [int]$Baud=115200,
    [string]$Timezone, [string]$UtcOffset, [string]$OutputDir, [string]$Manifest,
    [ValidateSet('qualification','calibration')][string]$CalibrationPurpose,
    [string]$QualificationAuthorization, [switch]$QualificationLineInput,
    [switch]$ListPorts, [switch]$Help,
    [string]$Python='C:\Users\LQY\Documents\Codex\node01-pc-console-venv\Scripts\python.exe'
)
$ErrorActionPreference='Stop'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw '独立PC环境未就绪；先运行tools\Setup-ExperimentConsole.ps1，禁止给SDK环境安装界面库' }
$nodeArgs=@('-X','utf8','-B','-m','experiment_console.console','--port',$Port,'--baud',[string]$Baud)
if ($Timezone) { $nodeArgs+=@('--timezone',$Timezone) }
if ($UtcOffset) { $nodeArgs+=@('--utc-offset='+$UtcOffset) }
if ($OutputDir) { $nodeArgs+=@('--output-dir',$OutputDir) }
if ($Manifest) { $nodeArgs+=@('--manifest',$Manifest) }
if ($CalibrationPurpose) { $nodeArgs+=@('--calibration-purpose',$CalibrationPurpose) }
if ($QualificationAuthorization) { $nodeArgs+=@('--qualification-authorization',$QualificationAuthorization) }
if ($QualificationLineInput) { $nodeArgs+='--qualification-line-input' }
if ($ListPorts) { $nodeArgs+='--list-ports' }
if ($Help) { $nodeArgs+='--help' }
Push-Location -LiteralPath $PSScriptRoot
try { & $Python @nodeArgs; if ($LASTEXITCODE -ne 0) { throw "PC控制台退出码 $LASTEXITCODE；保留原始报错，不代表设备已STOP" } }
finally { Pop-Location }
