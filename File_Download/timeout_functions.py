import time
import signal
import sys

# BELOW ONLY WORKS ON UNIX 
class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Time limit exceeded")

def run_with_timeout_sig(code_to_run, time_limit_seconds):
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(time_limit_seconds)
    try:
        exec(code_to_run)
        signal.alarm(0)  # Disable the alarm if the code completes in time
    except TimeoutException as e:
        print(e)
        sys.exit(1)
    except Exception as e:
         print(f"An error occurred: {e}")
         sys.exit(1)
    finally:
        signal.alarm(0) #
#####

from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from types import FunctionType
import textwrap, inspect, builtins

class TimeoutError(Exception):
    """Raised when the wrapped call exceeds its time limit."""

def run_with_timeout(callable_or_code, /, *args, timeout=2, cancel=True, **kwargs):
    """
    Run `callable_or_code(*args, **kwargs)` and return its result.
    
    Parameters
    ----------
    callable_or_code : callable | str
        • A normal Python function / lambda / callable object  
        • OR a string containing a single expression or a block of statements  
          (the string sees the caller's globals/locals).
    *args, **kwargs  : forwarded only when the first argument is callable.
    timeout          : seconds allowed before giving up (int | float).
    cancel           : if True, attempt to cancel the worker after a timeout.
    
    Returns
    -------
    Any
        Whatever the callable (or the last expression in the code string) produces.
    
    Raises
    ------
    TimeoutError      – if execution exceeds `timeout`.
    Exception         – any exception raised inside the user code itself.
    """
    
    # Wrap string input so we still submit a callable to the pool
    if isinstance(callable_or_code, str):
        src = textwrap.dedent(callable_or_code).strip()

        # Decide whether to eval (single expression) or exec (statements)
        try:
            compile(src, "<timeout-expr>", "eval")
            def _runner():
                return eval(src, inspect.currentframe().f_back.f_globals,
                                 inspect.currentframe().f_back.f_locals)
        except SyntaxError:
            def _runner():
                locs = {}
                exec(src, inspect.currentframe().f_back.f_globals, locs)
                # Return last assigned name or None
                return locs.get(next(reversed(locs)) , None)
    elif isinstance(callable_or_code, FunctionType) or callable(callable_or_code):
        def _runner():
            return callable_or_code(*args, **kwargs)
    else:
        raise TypeError("First argument must be a callable or a string of code.")

    # ---------- run it in a worker thread with a timeout ----------
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_runner)
        try:
            return future.result(timeout=timeout)
        except _FuturesTimeout:
            if cancel:
                future.cancel()
            raise TimeoutError(f"Call exceeded {timeout} s") from None