param([string]$Compiler = 'C:\msys64\ucrt64\bin\g++.exe', [string]$BuildDirectory = 'build-host')
$ErrorActionPreference = 'Stop'
$compilerDirectory = Split-Path (Get-Command $Compiler -ErrorAction Stop).Source -Parent
$env:PATH = "$compilerDirectory;$env:PATH"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$testBuild = Join-Path $projectRoot $BuildDirectory
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
$sdkInclude = 'C:\Users\LQY\Documents\Codex\esp55\esp-idf-v5.5.3\components\esp_common\include'
$sensorTest = Join-Path $testBuild 'sensors_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_board/include `
    -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/sensors_test.cpp components/node_drivers/sensors.cpp -o $sensorTest
if ($LASTEXITCODE -ne 0) { throw 'Sensor host compilation failed' }
& $sensorTest
if ($LASTEXITCODE -ne 0) { throw "Sensor tests failed: $LASTEXITCODE" }
Write-Output 'HOST_SENSOR_TEST_PASS (TEST_ONLY register simulation; no hardware I/O)'
$storageTest = Join-Path $testBuild 'storage_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Icomponents/node_storage/include -Ibuild-v01/config -I $sdkInclude `
    tests/storage_test.cpp components/node_storage/diagnostic_log.cpp -o $storageTest
if ($LASTEXITCODE -ne 0) { throw 'Storage host compilation failed' }
& $storageTest (Join-Path $testBuild ('storage-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')))
if ($LASTEXITCODE -ne 0) { throw "Storage tests failed: $LASTEXITCODE" }
Write-Output 'HOST_STORAGE_TEST_PASS (TEST_ONLY host filesystem; not MicroSD hardware)'
$telemetryTest = Join-Path $testBuild 'telemetry_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_comm/include `
    tests/telemetry_test.cpp components/node_comm/telemetry.cpp components/node_comm/identity.cpp `
    components/node_contracts/protocol.cpp -o $telemetryTest
if ($LASTEXITCODE -ne 0) { throw 'Telemetry/identity host compilation failed' }
& $telemetryTest
if ($LASTEXITCODE -ne 0) { throw "Telemetry/identity tests failed: $LASTEXITCODE" }
Write-Output 'HOST_TELEMETRY_IDENTITY_TEST_PASS (TEST_ONLY; NVS power-loss/Broker NOT_RUN)'
$runtimeTest = Join-Path $testBuild 'runtime_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Icomponents/node_runtime/include -Ibuild-v01/config -I $sdkInclude `
    tests/runtime_policy_test.cpp -o $runtimeTest
if ($LASTEXITCODE -ne 0) { throw 'Runtime policy host compilation failed' }
& $runtimeTest
if ($LASTEXITCODE -ne 0) { throw "Runtime policy tests failed: $LASTEXITCODE" }
Write-Output 'HOST_RUNTIME_POLICY_TEST_PASS (TEST_ONLY threads/queue/deadline/ADS never-ready; not FreeRTOS timing)'
$recoveryTest = Join-Path $testBuild 'storage_recovery_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Icomponents/node_storage/include -Ibuild-v01/config -I $sdkInclude `
    tests/storage_recovery_test.cpp components/node_storage/storage_recovery.cpp -o $recoveryTest
if ($LASTEXITCODE -ne 0) { throw 'Storage recovery host compilation failed' }
& $recoveryTest
if ($LASTEXITCODE -ne 0) { throw "Storage recovery tests failed: $LASTEXITCODE" }
Write-Output 'HOST_STORAGE_RECOVERY_TEST_PASS (TEST_ONLY injected mount/append/flush/verify/recovery failures)'
$networkTest = Join-Path $testBuild 'network_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_comm/include tests/network_policy_test.cpp -o $networkTest
if ($LASTEXITCODE -ne 0) { throw 'Network policy host compilation failed' }
& $networkTest
if ($LASTEXITCODE -ne 0) { throw "Network policy tests failed: $LASTEXITCODE" }
Write-Output 'HOST_NETWORK_POLICY_TEST_PASS (TEST_ONLY retry clocks/link event order; Wi-Fi/MQTT hardware NOT_RUN)'
$i2cPolicyTest = Join-Path $testBuild 'i2c_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Ibuild-v01/config -I $sdkInclude tests/i2c_policy_test.cpp -o $i2cPolicyTest
if ($LASTEXITCODE -ne 0) { throw 'I2C policy host compilation failed' }
& $i2cPolicyTest
if ($LASTEXITCODE -ne 0) { throw "I2C policy tests failed: $LASTEXITCODE" }
Write-Output 'HOST_I2C_FAULT_POLICY_TEST_PASS (TEST_ONLY tick phases/address diagnostics; hardware NEED_HARDWARE_RETEST)'
$modeTest = Join-Path $testBuild 'diagnostic_mode_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include tests/diagnostic_mode_test.cpp -o $modeTest
if ($LASTEXITCODE -ne 0) { throw 'Diagnostic mode host compilation failed' }
& $modeTest
if ($LASTEXITCODE -ne 0) { throw "Diagnostic mode tests failed: $LASTEXITCODE" }
Write-Output 'HOST_DIAGNOSTIC_MODE_TEST_PASS (TEST_ONLY isolation selection and synthetic input count; no hardware rate claim)'
$captureTest = Join-Path $testBuild 'acquisition_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include tests/acquisition_policy_test.cpp -o $captureTest
if ($LASTEXITCODE -ne 0) { throw 'Acquisition policy host compilation failed' }
& $captureTest
if ($LASTEXITCODE -ne 0) { throw "Acquisition policy tests failed: $LASTEXITCODE" }
Write-Output 'HOST_ACQUISITION_POLICY_TEST_PASS (TEST_ONLY cutoff/stop/IRQ coalescence/tick wrap; no hardware claim)'
$irqGateTest = Join-Path $testBuild 'imu_irq_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_drivers/include tests/imu_irq_policy_test.cpp -o $irqGateTest
if ($LASTEXITCODE -ne 0) { throw 'IMU IRQ gate host compilation failed' }
& $irqGateTest
if ($LASTEXITCODE -ne 0) { throw "IMU IRQ gate tests failed: $LASTEXITCODE" }
Write-Output 'HOST_IMU_IRQ_GATE_TEST_PASS (TEST_ONLY ready/arm/stale/capture baseline; not physical interrupt validation)'

$startupTest = Join-Path $testBuild 'startup_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_drivers/include -Icomponents/node_storage/include `
    -Ibuild-v01/config -I $sdkInclude tests/startup_policy_test.cpp `
    components/node_storage/storage_recovery.cpp -o $startupTest
if ($LASTEXITCODE -ne 0) { throw 'Startup policy host compilation failed' }
& $startupTest
if ($LASTEXITCODE -ne 0) { throw "Startup policy tests failed: $LASTEXITCODE" }
$imuServiceTest = Join-Path $testBuild 'imu_service_policy_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_drivers/include `
    tests/imu_service_policy_test.cpp -o $imuServiceTest
if ($LASTEXITCODE -ne 0) { throw 'IMU service policy host compilation failed' }
& $imuServiceTest
if ($LASTEXITCODE -ne 0) { throw "IMU service policy tests failed: $LASTEXITCODE" }
$imuInitStateTest = Join-Path $testBuild 'imu_init_state_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_board/include `
    -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/imu_init_state_test.cpp components/node_drivers/sensors.cpp -o $imuInitStateTest
if ($LASTEXITCODE -ne 0) { throw 'IMU initialization state host compilation failed' }
& $imuInitStateTest
if ($LASTEXITCODE -ne 0) { throw "IMU initialization state tests failed: $LASTEXITCODE" }
$i2cExecutorTest = Join-Path $testBuild 'i2c_executor_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/i2c_executor_test.cpp -o $i2cExecutorTest
if ($LASTEXITCODE -ne 0) { throw 'I2C executor host compilation failed' }
& $i2cExecutorTest
if ($LASTEXITCODE -ne 0) { throw "I2C executor tests failed: $LASTEXITCODE" }
$storagePressureTest = Join-Path $testBuild 'storage_pressure_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_drivers/include -Icomponents/node_storage/include `
    -Ibuild-v01/config -I $sdkInclude tests/storage_pressure_test.cpp `
    components/node_storage/storage_recovery.cpp -o $storagePressureTest
if ($LASTEXITCODE -ne 0) { throw 'Storage pressure host compilation failed' }
& $storagePressureTest
if ($LASTEXITCODE -ne 0) { throw "Storage pressure tests failed: $LASTEXITCODE" }
$storageIoTest = Join-Path $testBuild 'storage_io_fault_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Icomponents/node_storage/include -Ibuild-v01/config -I $sdkInclude `
    tests/storage_io_fault_test.cpp components/node_storage/diagnostic_log.cpp `
    components/node_storage/storage_recovery.cpp `
    '-Wl,--wrap=fwrite,--wrap=fflush,--wrap=fclose,--wrap=read,--wrap=__imp__commit' -o $storageIoTest
if ($LASTEXITCODE -ne 0) { throw 'Storage I/O fault host compilation failed' }
# Keep the injected host path within DiagnosticLog's real 128-byte path limit.
# Test-Host already owns project cwd; a relative unique fixture avoids masking
# that firmware bound by enlarging a production buffer just for Windows paths.
$storageIoRoot = Join-Path $BuildDirectory ('storage-io-fault-' + [guid]::NewGuid().ToString('N'))
& $storageIoTest $storageIoRoot
if ($LASTEXITCODE -ne 0) { throw "Storage I/O fault tests failed: $LASTEXITCODE" }

$storageLatencyTest = Join-Path $testBuild 'storage_latency_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include tests/storage_latency_test.cpp -o $storageLatencyTest
if ($LASTEXITCODE -ne 0) { throw 'Storage latency diagnostic compilation failed' }
& $storageLatencyTest
if ($LASTEXITCODE -ne 0) { throw "Storage latency diagnostic tests failed: $LASTEXITCODE" }

$i2cLockTraceTest = Join-Path $testBuild 'i2c_lock_trace_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/i2c_lock_trace_test.cpp -o $i2cLockTraceTest
if ($LASTEXITCODE -ne 0) { throw 'I2C ownership diagnostic compilation failed' }
& $i2cLockTraceTest
if ($LASTEXITCODE -ne 0) { throw "I2C ownership diagnostic tests failed: $LASTEXITCODE" }

$adsContentionTest = Join-Path $testBuild 'ads_contention_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_board/include -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/ads_contention_test.cpp components/node_drivers/sensors.cpp -o $adsContentionTest
if ($LASTEXITCODE -ne 0) { throw 'ADS contention test compilation failed' }
& $adsContentionTest
if ($LASTEXITCODE -ne 0) { throw "ADS contention tests failed: $LASTEXITCODE" }

$experimentControlTest = Join-Path $testBuild 'experiment_control_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -Icomponents/node_runtime/include `
    tests/experiment_control_test.cpp -o $experimentControlTest
if ($LASTEXITCODE -ne 0) { throw 'Experiment control compilation failed' }
& $experimentControlTest
if ($LASTEXITCODE -ne 0) { throw "Experiment control tests failed: $LASTEXITCODE" }

$experimentMetadataTest = Join-Path $testBuild 'experiment_metadata_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -Icomponents/node_storage/include `
    tests/experiment_metadata_test.cpp components/node_storage/experiment_metadata.cpp `
    '-Wl,--wrap=fwrite,--wrap=fflush,--wrap=fclose,--wrap=fopen,--wrap=fread,--wrap=__imp__commit' -o $experimentMetadataTest
if ($LASTEXITCODE -ne 0) { throw 'Experiment metadata compilation failed' }
$metadataFixture = Join-Path $BuildDirectory ('em-' + [guid]::NewGuid().ToString('N').Substring(0,8))
& $experimentMetadataTest ($metadataFixture.Replace('\','/'))
if ($LASTEXITCODE -ne 0) { throw "Experiment metadata tests failed: $LASTEXITCODE" }

$experimentLifecycleTest = Join-Path $testBuild 'experiment_lifecycle_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include -Icomponents/node_drivers/include `
    -Icomponents/node_storage/include -Ibuild-v01/config -I $sdkInclude `
    tests/experiment_lifecycle_test.cpp components/node_storage/diagnostic_log.cpp `
    components/node_storage/storage_recovery.cpp components/node_storage/experiment_metadata.cpp -o $experimentLifecycleTest
if ($LASTEXITCODE -ne 0) { throw 'Experiment lifecycle compilation failed' }
$lifecycleFixture = Join-Path $BuildDirectory ('el-' + [guid]::NewGuid().ToString('N').Substring(0,8))
& $experimentLifecycleTest ($lifecycleFixture.Replace('\','/'))
if ($LASTEXITCODE -ne 0) { throw "Experiment lifecycle tests failed: $LASTEXITCODE" }

$finiteTraceTest = Join-Path $testBuild 'i2c_finite_trace_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -Icomponents/node_runtime/include -Icomponents/node_drivers/include tests/i2c_finite_trace_test.cpp -o $finiteTraceTest
if ($LASTEXITCODE -ne 0) { throw 'Finite I2C diagnostic compilation failed' }
& $finiteTraceTest
if ($LASTEXITCODE -ne 0) { throw "Finite I2C diagnostic tests failed: $LASTEXITCODE" }

$schedulerFixTest = Join-Path $testBuild 'i2c_scheduler_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_runtime/include tests/i2c_scheduler_test.cpp -o $schedulerFixTest
if ($LASTEXITCODE -ne 0) { throw 'I2C scheduler/deferred notice compilation failed' }
& $schedulerFixTest
if ($LASTEXITCODE -ne 0) { throw "I2C scheduler/deferred notice tests failed: $LASTEXITCODE" }

$traceOutputTest = Join-Path $testBuild 'i2c_trace_output_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_runtime/include -Icomponents/node_drivers/include `
    tests/i2c_trace_output_test.cpp -o $traceOutputTest
if ($LASTEXITCODE -ne 0) { throw 'Bounded diagnostic output/window compilation failed' }
& $traceOutputTest
if ($LASTEXITCODE -ne 0) { throw "Bounded diagnostic output/window tests failed: $LASTEXITCODE" }

$readRetryTest = Join-Path $testBuild 'i2c_read_retry_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_board/include -Icomponents/node_drivers/include -Ibuild-v01/config -I $sdkInclude `
    tests/i2c_read_retry_test.cpp components/node_drivers/sensors.cpp -o $readRetryTest
if ($LASTEXITCODE -ne 0) { throw 'I2C bounded read retry compilation failed' }
& $readRetryTest
if ($LASTEXITCODE -ne 0) { throw "I2C bounded read retry tests failed: $LASTEXITCODE" }
Write-Output 'HOST_I2C_READ_RETRY_PASS (TEST_ONLY; no bus reset, writes/status/sample replay, or hardware claim)'

$pacingTest = Join-Path $testBuild 'storage_readback_pacing_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic -pthread `
    -Icomponents/node_runtime/include -Icomponents/node_contracts/include `
    -Icomponents/node_drivers/include -Icomponents/node_storage/include -Ibuild-v01/config -I $sdkInclude `
    tests/storage_readback_pacing_test.cpp components/node_storage/storage_recovery.cpp -o $pacingTest
if ($LASTEXITCODE -ne 0) { throw 'Storage readback quota model compilation failed' }
& $pacingTest
if ($LASTEXITCODE -ne 0) { throw "Storage readback quota model tests failed: $LASTEXITCODE" }

$toeProtocolTest = Join-Path $testBuild 'toe_bench_protocol_test.exe'
& $Compiler -std=c++17 -Wall -Wextra -Werror -pedantic `
    -DCONFIG_NODE01_TOE_BENCH_QUEUE_SD=1 -DCONFIG_NODE01_REAL_TEST_ONLY=1 -DCONFIG_NODE01_CAPTURE_SECONDS=120 `
    -Icomponents/node_runtime/include tests/toe_bench_protocol_test.cpp -o $toeProtocolTest
if ($LASTEXITCODE -ne 0) { throw 'TOE bench protocol test compilation failed' }
& $toeProtocolTest
if ($LASTEXITCODE -ne 0) { throw "TOE bench protocol tests failed: $LASTEXITCODE" }
