param([string]$Compiler = 'g++')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$testBuild = Join-Path $projectRoot 'build-host'
New-Item -ItemType Directory -Force -Path $testBuild | Out-Null
$executable = Join-Path $testBuild 'logic_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_logic/include `
    tests/logic_test.cpp components/node_contracts/protocol.cpp components/node_logic/logic.cpp `
    -o $executable
if ($LASTEXITCODE -ne 0) { throw 'Host C++17 compilation failed' }
& $executable
if ($LASTEXITCODE -ne 0) { throw "Host logic tests failed: $LASTEXITCODE" }
Write-Output 'HOST_LOGIC_TEST_PASS (TEST_ONLY; not ESP-IDF or hardware validation)'
