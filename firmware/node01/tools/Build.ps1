param([string]$BuildDirectory = 'build', [string]$RecordDirectory = '', [string]$Sdkconfig = 'sdkconfig')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path (Split-Path $projectRoot -Parent) -Parent
$configPath = if ([System.IO.Path]::IsPathRooted($Sdkconfig)) { $Sdkconfig } else { Join-Path $projectRoot $Sdkconfig }
$configPath = [System.IO.Path]::GetFullPath($configPath)
if (-not $RecordDirectory) {
    $RecordDirectory = Join-Path $repoRoot ('docs\test_records\NODE-01\' + (Get-Date -Format 'yyyy-MM-dd-HHmmss') + '-v01')
}
$recordRoot = [System.IO.Path]::GetFullPath($RecordDirectory)
if (Test-Path -LiteralPath $recordRoot) { throw "Refusing to overwrite test evidence: $recordRoot" }
New-Item -ItemType Directory -Path $recordRoot | Out-Null
$result = [ordered]@{ build='NOT_RUN'; target='esp32s3'; idf=$null; exit_code=$null; reason=$null }
try {
    . (Join-Path $PSScriptRoot 'Activate-ESP-IDF.ps1')
    Set-Location -LiteralPath $projectRoot
    $result.idf = (idf.py --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'idf.py version check failed' }
    @($result.idf, "IDF_PATH=$env:IDF_PATH", (cmake --version), (ninja --version)) |
        Set-Content -LiteralPath (Join-Path $recordRoot 'environment.log') -Encoding utf8
    if (-not (Select-String -LiteralPath $configPath -Pattern '^CONFIG_IDF_TARGET="esp32s3"$' -Quiet)) {
        throw 'Target mismatch; inspect configuration before manually setting target.'
    }
    # Reused validated sdkconfig already sets target; do not run set-target destructively.
    $result.build = 'FAIL'
    # Windows PowerShell 5 turns native stderr into ErrorRecord; do not abort
    # before recording the native process exit code and the complete log.
    $ErrorActionPreference = 'Continue'
    idf.py -B $BuildDirectory "-DSDKCONFIG=$configPath" build 2>&1 | Tee-Object -FilePath (Join-Path $recordRoot 'build.log')
    $result.exit_code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "idf.py build failed: $LASTEXITCODE" }
    foreach ($expected in @('CONFIG_SPIRAM=y', 'CONFIG_SPIRAM_MODE_OCT=y',
            'CONFIG_SPIRAM_SPEED_80M=y', 'CONFIG_SPIRAM_MEMTEST=y', 'CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y')) {
        if (-not (Select-String -LiteralPath $configPath -Pattern ('^' + [regex]::Escape($expected) + '$') -Quiet)) {
            throw "Expected baseline configuration missing: $expected"
        }
    }
    foreach ($artifact in @('zhishao_node01.bin', 'zhishao_node01.elf')) {
        $artifactPath = Join-Path $BuildDirectory $artifact
        if (-not (Test-Path -LiteralPath $artifactPath)) { throw "Missing artifact: $artifact" }
    }
    $result['bin_sha256'] = (Get-FileHash -LiteralPath (Join-Path $BuildDirectory 'zhishao_node01.bin') -Algorithm SHA256).Hash
    $result['bin_bytes'] = (Get-Item -LiteralPath (Join-Path $BuildDirectory 'zhishao_node01.bin')).Length
    $result['sdkconfig_sha256'] = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    $result['sdkconfig'] = $configPath
    $result['configuration_check'] = 'PASS (not hardware validation)'
    $result.build = 'PASS'
} catch {
    $result.reason = $_.Exception.Message
    Write-Warning $result.reason
} finally {
    $result['completed_at'] = (Get-Date).ToString('o')
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $recordRoot 'build-result.json') -Encoding utf8
    Set-Location -LiteralPath $projectRoot
}
if ($result.build -ne 'PASS') { exit 1 }
