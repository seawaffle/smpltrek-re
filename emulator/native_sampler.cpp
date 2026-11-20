// Optional Linux process-CPU sampler. Runs only in the profiling process, outside the guest ABI.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <cstdint>
#include <csignal>
#include <atomic>
#include <sys/time.h>
#include <time.h>
#include <ucontext.h>

namespace {
constexpr unsigned CAPACITY = 262144;
std::atomic<uintptr_t> samples[CAPACITY]{};
static_assert(std::atomic<uintptr_t>::is_always_lock_free);
volatile sig_atomic_t count = 0, dropped = 0;
struct sigaction saved_action;
struct itimerval saved_timer;
bool active = false;
void sample(int, siginfo_t *, void *context) {
    auto *state = static_cast<ucontext_t *>(context);
#if defined(__x86_64__)
    uintptr_t pc = state->uc_mcontext.gregs[REG_RIP];
#elif defined(__aarch64__)
    uintptr_t pc = state->uc_mcontext.pc;
#else
#error Native sampling supports Linux x86_64 and aarch64
#endif
    sig_atomic_t next = count;
    if (next < sig_atomic_t(CAPACITY)) { samples[next].store(pc, std::memory_order_relaxed); count = next + 1; }
    else dropped = dropped + 1;
}
}
extern "C" {
int sample_start(unsigned interval_us) {
    if (active || !interval_us || interval_us > 1000000) return -1;
    struct sigaction action{}; action.sa_sigaction = sample; action.sa_flags = SA_SIGINFO | SA_RESTART;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGPROF, &action, &saved_action)) return -1;
    count = 0; dropped = 0;
    struct itimerval timer{};
    timer.it_interval.tv_sec = interval_us / 1000000;
    timer.it_interval.tv_usec = interval_us % 1000000;
    timer.it_value = timer.it_interval;
    if (setitimer(ITIMER_PROF, &timer, &saved_timer)) { sigaction(SIGPROF, &saved_action, nullptr); return -1; }
    active = true; return 0;
}
int sample_stop() {
    if (!active) return -1;
    sigset_t blocked, previous;
    sigemptyset(&blocked); sigaddset(&blocked, SIGPROF);
    if (sigprocmask(SIG_BLOCK, &blocked, &previous)) return -1;
    struct itimerval timer{}; setitimer(ITIMER_PROF, &timer, nullptr);
    struct timespec zero{};
    while (sigtimedwait(&blocked, nullptr, &zero) == SIGPROF) {}
    sigaction(SIGPROF, &saved_action, nullptr);
    setitimer(ITIMER_PROF, &saved_timer, nullptr);
    active = false;
    return sigprocmask(SIG_SETMASK, &previous, nullptr);
}
unsigned sample_count() { return count; }
unsigned sample_dropped() { return dropped; }
uintptr_t sample_pc(unsigned index) { return index < unsigned(count) ? samples[index].load(std::memory_order_relaxed) : 0; }
}
