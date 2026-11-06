"""Process memory readings for explicitly measured local operations."""
import os
import ctypes
import sys


def memory_usage():
    if os.name=='nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(key,ctypes.c_size_t) for key in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
            return {'memory_unavailable':True}
        return dict(working_set_bytes=int(counters.WorkingSetSize),peak_working_set_bytes=int(counters.PeakWorkingSetSize),
                    private_commit_bytes=int(counters.PagefileUsage),peak_private_commit_bytes=int(counters.PeakPagefileUsage))
    import resource
    return dict(peak_working_set_bytes=rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,sys.platform))


def rss_bytes(value,platform):
    """Darwin ru_maxrss is bytes; Linux ru_maxrss is KiB."""
    return int(value) if platform=='darwin' else int(value)*1024
