"""One expressive model resident at a time across workers and qualification tools."""
import fcntl
import os
from pathlib import Path

_lease_fd = None


def acquire_model_lease():
    """Hold a kernel lock until process exit; stale files do not imply a live owner."""
    global _lease_fd
    if _lease_fd is not None:
        return
    folder = Path.home()/'.local/state/afterwords'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd = os.open(folder/'expressive-model.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError('another expressive model is resident; release the idle sidecar before benchmarking') from None
    _lease_fd = fd
