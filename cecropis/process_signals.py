"""Map POSIX termination to the same cleanup path as Ctrl+C, on the main thread."""
import signal
import sys
import threading
from contextlib import contextmanager


@contextmanager
def termination_as_interrupt():
    if sys.platform=='win32' or threading.current_thread() is not threading.main_thread():
        yield
        return
    def interrupt(*_):
        raise KeyboardInterrupt
    previous=signal.signal(signal.SIGTERM,interrupt)
    try:yield
    finally:signal.signal(signal.SIGTERM,previous)
