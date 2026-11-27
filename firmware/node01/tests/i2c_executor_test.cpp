#include "node/runtime_policy.hpp"
#include "esp_err.h"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <future>
#include <mutex>
#include <thread>

// TEST_ONLY: the same ownership policy used by Runtime, with injected Take,
// Give and SDK return values. Real host timed_mutex tests are not FreeRTOS,
// ESP-IDF I2C, electrical validation or a hardware timing guarantee.
namespace {
using node::runtime::policy::locked_transaction;
using namespace std::chrono_literals;

void failed_take_never_executes_or_releases() {
    unsigned takes = 0, gives = 0, sdk_calls = 0;
    const auto result = locked_transaction(
        [&] { ++takes; return false; },
        [&] { ++gives; },
        [&] { ++sdk_calls; return ESP_OK; }, ESP_ERR_TIMEOUT);
    assert(result == ESP_ERR_TIMEOUT);
    assert(takes == 1 && gives == 0 && sdk_calls == 0);
}

void acquired_results_are_preserved_and_released_once() {
    for (esp_err_t sdk_result : {ESP_OK, ESP_ERR_INVALID_STATE}) {
        unsigned takes = 0, gives = 0, sdk_calls = 0;
        bool held = false;
        const auto result = locked_transaction(
            [&] { ++takes; held = true; return true; },
            [&] { assert(held); ++gives; held = false; },
            [&] { assert(held); ++sdk_calls; return sdk_result; }, ESP_ERR_TIMEOUT);
        assert(result == sdk_result);
        assert(takes == 1 && gives == 1 && sdk_calls == 1 && !held);
    }
}

void real_mutex_is_held_during_run_and_available_after_return() {
    for (esp_err_t sdk_result : {ESP_OK, ESP_ERR_INVALID_STATE}) {
        std::timed_mutex mutex;
        unsigned gives = 0, sdk_calls = 0;
        bool another_thread_acquired = true;
        const auto result = locked_transaction(
            [&] { return mutex.try_lock_for(50ms); },
            [&] { ++gives; mutex.unlock(); },
            [&] {
                ++sdk_calls;
                // Do not try_lock a nonrecursive mutex from its owning thread.
                // Join this contender before Run returns, so the executor still
                // owns the mutex for the contender's entire observation.
                std::thread contender([&] {
                    another_thread_acquired = mutex.try_lock_for(2ms);
                    if (another_thread_acquired) mutex.unlock();
                });
                contender.join();
                return sdk_result;
            }, ESP_ERR_TIMEOUT);
        assert(result == sdk_result && gives == 1 && sdk_calls == 1);
        assert(!another_thread_acquired);
        const bool reacquired = mutex.try_lock_for(50ms);
        assert(reacquired);
        if (reacquired) mutex.unlock();
    }
}

void another_owner_is_never_released_after_take_timeout() {
    std::timed_mutex mutex;
    std::promise<void> owns_mutex, may_release;
    auto owner_ready = owns_mutex.get_future();
    auto release_owner = may_release.get_future();
    std::thread owner([&] {
        mutex.lock();
        owns_mutex.set_value();
        release_owner.wait();
        mutex.unlock();
    });
    owner_ready.wait(); // deterministic ownership, no sleep-based ordering
    unsigned takes = 0, gives = 0, sdk_calls = 0;
    const auto result = locked_transaction(
        [&] { ++takes; return mutex.try_lock_for(2ms); },
        [&] { ++gives; }, // intentionally never unlock another thread's mutex
        [&] { ++sdk_calls; return ESP_OK; }, ESP_ERR_TIMEOUT);
    assert(result == ESP_ERR_TIMEOUT && takes == 1 && gives == 0 && sdk_calls == 0);
    // A failed Take did not change ownership. The owner cannot release until
    // this thread explicitly allows it below.
    const bool stolen = mutex.try_lock_for(2ms);
    assert(!stolen);
    if (stolen) mutex.unlock();
    may_release.set_value(); owner.join();
    const bool reacquired = mutex.try_lock_for(50ms);
    assert(reacquired);
    if (reacquired) mutex.unlock();
}

void host_only_exception_releases_once() {
    // Host-only C++ exception test for the generic RAII boundary. ESP-IDF SDK
    // callbacks return esp_err_t; this does not claim SDK exception behavior.
    struct InjectedFailure {};
    std::timed_mutex mutex;
    unsigned gives = 0, sdk_calls = 0;
    bool caught = false;
    try {
        (void)locked_transaction(
            [&] { return mutex.try_lock_for(50ms); },
            [&] { ++gives; mutex.unlock(); },
            [&]() -> esp_err_t { ++sdk_calls; throw InjectedFailure{}; }, ESP_ERR_TIMEOUT);
    } catch (const InjectedFailure&) { caught = true; }
    assert(caught && gives == 1 && sdk_calls == 1);
    const bool reacquired = mutex.try_lock_for(50ms);
    assert(reacquired);
    if (reacquired) mutex.unlock();
}
} // namespace

int main() {
    failed_take_never_executes_or_releases();
    acquired_results_are_preserved_and_released_once();
    real_mutex_is_held_during_run_and_available_after_return();
    another_owner_is_never_released_after_take_timeout();
    host_only_exception_releases_once();
    std::puts("HOST_I2C_EXECUTOR_TEST_PASS (TEST_ONLY injected Take/Give/SDK results and host timed_mutex; FreeRTOS NOT_RUN)");
}
