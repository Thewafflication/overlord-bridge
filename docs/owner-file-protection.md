# Windows free-worker deletion protection

A WCRT worker removed pre-existing `owned-debug.bin` using Python `os.remove`,
despite explicit preservation instructions. A clean Git status and a positive
completion review did not detect this untracked-file loss. No original bytes
were recovered. This fix prevents the observed cleanup mechanism for future runs.

Before a Windows free worker's first model action, Overlord inventories existing
nonignored untracked and modified/staged tracked files using Git path metadata.
Initialized nested repositories are included. For loose-script folders, it walks
allowed paths without following directory links. Inventories are bounded to
20,000 files, 100 repositories and 2 MB per Git query; incomplete enumeration or
failure to open any selected file stops admission, before model tools run.

Each selected file is opened with GENERIC_READ, FILE_SHARE_READ and
FILE_SHARE_WRITE, without FILE_SHARE_DELETE. No file contents are read and no
handle is inherited by subprocesses. Windows rejects subsequent deletion,
rename and replacement through ordinary Python, PowerShell and native APIs.
Metadata-only handles did not block deletion in the native regression probe.
[Microsoft documents the sharing contract and its handle lifetime.](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

Handles remain open during model execution and worker cleanup and are released
before the running-worker slot becomes idle, including cancellation and crashes.
Protection admission failures release any handles already acquired. The policy
is given to the model so a sharing violation is treated as final, not bypassed.

This is deletion protection, not an overwrite backup or an arbitrary-code
sandbox. Authorized in-place edits remain possible. Atomic-save editors cannot
replace protected files while the worker runs. Clean committed files and files
created during the job remain deletable; Git already preserves committed data.
Ignored/generated and off-limits paths, symbolic links, other worker brains and
non-Windows hosts are outside this guard. The guard makes no ACL changes and
does not recover files deleted by earlier versions.

Tests execute real child-process deletion, rename, replacement and Windows
PowerShell removal against isolated fixtures; verify retained bytes, in-place
edits, new scratch cleanup and post-job release; cover Git/submodule inventories,
partial acquisition failure and completion/crash/cancellation lifecycle. A full
WorkerManager regression repeats the observed `os.remove('owned-debug.bin')`
tool call and verifies that owner data survives and idle cleanup releases it.
