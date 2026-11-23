$ErrorActionPreference = 'Stop'
$espEnvironmentRoot = 'C:\Users\LQY\Documents\Codex\esp55'
$env:IDF_PATH = Join-Path $espEnvironmentRoot 'esp-idf-v5.5.3'
$env:IDF_TOOLS_PATH = Join-Path $espEnvironmentRoot 'tools'
$env:IDF_PYTHON_ENV_PATH = Join-Path $env:IDF_TOOLS_PATH 'python_env\idf5.5_py3.12_env'
$env:IDF_GITHUB_ASSETS = 'dl.espressif.com/github_assets'
# Some Windows launchers supply both PATH and Path. Python folds names to
# uppercase and may then retain the stale value. Recreate a single entry.
$espOriginalPath = $env:Path
Remove-Item Env:Path -ErrorAction SilentlyContinue
$env:PATH = "$espEnvironmentRoot\python;$espEnvironmentRoot\git\cmd;$espOriginalPath"

# Trust only the installed SDK repositories in this process and its children.
# Installation and interactive development can run under different accounts.
$espTrustConfig = Join-Path $PSScriptRoot 'sdk-safe.gitconfig'
$espConfigCount = 0
if ($env:GIT_CONFIG_COUNT) { $espConfigCount = [int]$env:GIT_CONFIG_COUNT }
$espTrustConfigured = $false
for ($espConfigIndex = 0; $espConfigIndex -lt $espConfigCount; $espConfigIndex++) {
    if ([Environment]::GetEnvironmentVariable("GIT_CONFIG_KEY_$espConfigIndex") -eq 'include.path' -and
        [Environment]::GetEnvironmentVariable("GIT_CONFIG_VALUE_$espConfigIndex") -eq $espTrustConfig) {
        $espTrustConfigured = $true
    }
}
if (-not $espTrustConfigured) {
    [Environment]::SetEnvironmentVariable("GIT_CONFIG_KEY_$espConfigCount", 'include.path', 'Process')
    [Environment]::SetEnvironmentVariable("GIT_CONFIG_VALUE_$espConfigCount", $espTrustConfig, 'Process')
    $env:GIT_CONFIG_COUNT = [string]($espConfigCount + 1)
}

$espTag = & "$espEnvironmentRoot\git\cmd\git.exe" -C $env:IDF_PATH describe --tags --exact-match HEAD
if ($LASTEXITCODE -ne 0 -or $espTag -ne 'v5.5.3') {
    throw "Expected ESP-IDF tag v5.5.3, found '$espTag'."
}
$espCommit = & "$espEnvironmentRoot\git\cmd\git.exe" -C $env:IDF_PATH rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $espCommit -ne '2c211b236707889e8400c4dc5644dd5c4ee071e0') {
    throw "ESP-IDF commit does not match the pinned v5.5.3 release: $espCommit"
}
. "$env:IDF_PATH\export.ps1"
if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF environment activation failed.' }
$espActivatedPath = $env:PATH
Remove-Item Env:Path -ErrorAction SilentlyContinue
$env:PATH = $espActivatedPath
Set-Location $PSScriptRoot
