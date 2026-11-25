param(
    [string]$SdDirectory,
    [string]$Session, [string]$Manifest, [string]$ExperimentId, [string]$OutputDir,
    [switch]$Copy, [switch]$Help,
    [string]$Python='C:\Users\LQY\Documents\Codex\node01-pc-console-venv\Scripts\python.exe'
)
$ErrorActionPreference='Stop'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw '独立PC Python不存在，请先Setup-ExperimentConsole.ps1' }
$nodeArgs=@('-X','utf8','-B','-m','experiment_console.archive')
if ($Help) { $nodeArgs+='--help' }
elseif ($SdDirectory) { $nodeArgs+=@('--sd-dir',$SdDirectory) }
else { throw '需要-SdDirectory源目录；查看-Help' }
if ($Session) { $nodeArgs+=@('--session',$Session) }
if ($Manifest) { $nodeArgs+=@('--manifest',$Manifest) }
if ($ExperimentId) { $nodeArgs+=@('--experiment-id',$ExperimentId) }
if ($OutputDir) { $nodeArgs+=@('--output-dir',$OutputDir) }
if ($Copy) { $nodeArgs+='--copy' } else { $nodeArgs+='--dry-run' }
Push-Location -LiteralPath $PSScriptRoot
try { & $Python @nodeArgs; if ($LASTEXITCODE -ne 0) { throw '归档/预览未通过；没有HOST_FILES_VERIFIED，不修改SD原件。检查上方原始原因。' } }
finally { Pop-Location }
