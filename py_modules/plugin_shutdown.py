"""Bounded Decky shutdown; never inspect or signal unrelated processes."""
import asyncio
import os
import signal
import threading
import time


def signal_compiler(process, sig):
    """Manager owns this live Popen; its compiler starts a separate session."""
    if process is None or process.poll() is not None:
        return False
    if os.name != 'posix':
        # Decky is Linux-only. Never infer a Windows process-group identity.
        return False
    try:
        if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
            return False
        os.killpg(process.pid, sig)
        return True
    except ProcessLookupError:
        return False


async def shutdown_plugin(manager, monitor, update_task, logger, *, budget=4.0, grace=0.75):
    deadline = time.monotonic() + budget
    monitor.request_close()
    update_task.cancel()
    # The shared cancellation event stops all preparation jobs. Signal the
    # compiler below only after validating its owned session identity.
    manager.request_shutdown()

    # A monitor configure call may be waiting on a filesystem read. Do not put
    # its cleanup in asyncio's executor, whose shutdown can outlive this budget.
    monitor_done = threading.Event()
    def close_monitor():
        try:
            monitor.close(deadline=deadline)
        except Exception as exc:
            logger.warning('Status monitor shutdown: %s', exc)
        finally:
            monitor_done.set()
    threading.Thread(target=close_monitor, daemon=True, name='HelixSR-shutdown').start()
    observed = {}
    while time.monotonic() < deadline:
        process = manager.process
        if process is not None and process.poll() is None:
            now = time.monotonic()
            try:
                if process not in observed:
                    observed[process] = now
                    if not signal_compiler(process, signal.SIGTERM):
                        logger.warning('Compiler shutdown refused: owned child is not a live session leader')
                elif now - observed[process] >= grace:
                    signal_compiler(process, signal.SIGKILL)
            except OSError as exc:
                logger.warning('Compiler shutdown: %s', exc)
        worker = manager.worker
        if (monitor_done.is_set() and not (worker and worker.is_alive()) and update_task.done()
                and (process is None or process.poll() is not None)):
            break
        await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
    if update_task.done() and not update_task.cancelled():
        try:
            update_task.result()
        except Exception as exc:
            logger.warning('Plugin update shutdown: %s', exc)
    if manager.worker and manager.worker.is_alive():
        logger.warning('Shutdown deadline reached; active transaction journals and game files retained')
