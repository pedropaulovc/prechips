"""Worker ``freecadcmd`` processes that run the FreeCAD engine's independent booleans early.

``freecad_job.py`` measures every fact in one process, and most of its time goes to
booleans whose operands are all known before the loop that needs them: each printed
checkpoint row against its op's stock, each reach or flute pose against the stock it meets.
:class:`Pool` starts worker processes (``freecadcmd freecad_job.py -- --pool ADDRESS
DIRECTORY``); a :class:`Batch` hands them one loop's calls in the order the loop takes
them, and the loop takes each answer (:func:`answer`) where it would have computed it.

A pooled call runs one of the engine's own functions on bit-identical copies of its shapes,
so its answer is the one the engine would compute:

* Shapes cross processes only as OCC binary B-rep (``exportBinary``/``importBinary``), which
  keeps every double, tolerance, location and orientation, and the sub-shapes the shapes of
  one :meth:`Batch.submit` share with each other.
* FreeCAD runs OCC booleans non-destructively, so they leave their arguments unchanged and
  the same call on the same structure is the computation the engine would run (whose
  output can differ in its last digits from one engine run to the next, with or without
  workers). A boolean also reads its arguments' triangulation (FreeCAD's fuzzy value and
  OCC's interference boxes come from ``BRepBndLib::Add``), which binary B-rep drops:
  shapes with a triangulated face are never shared, so their calls stay the engine's.
* A returned shape shares no sub-shape with any engine shape. The engine only measures it or
  combines it with fresh solids; where it would meet a shape it could share sub-shapes with
  in-process, the engine recomputes it instead.

The pool only ever saves time: a call no worker has started, or whose worker failed, was
lost or raised, is left to the engine, which computes it itself (raising as before). A
loop's calls it never takes are cancelled when its batch closes.

No worker outlives the engine, however the engine ends: the host's runaway guard kills it
without running its cleanup, possibly while a worker is inside a boolean that cannot notice.
On Windows the engine first puts itself in a job object that kills every process in it when
its one handle closes, which the system does as the engine ends; its workers are born in
that job. On Linux each worker has the kernel kill it when its parent dies. Elsewhere no
worker starts. The workers' shape files live in a directory beside the job's output file,
in the host's own job directory, which the host removes even after killing the engine.
"""

from __future__ import annotations

import collections
import ctypes
import itertools
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener, wait

import Part

DEPTH = 2  # calls in flight per worker: one running, one waiting
KEY_ENV = "PRECHIPS_POOL_KEY"  # the listener's authentication key, for workers only
PARENT_ENV = "PRECHIPS_POOL_PARENT"  # the engine's process id, for workers only

_JOB = None  # Windows: this engine's kill-on-close job handle (0 when unavailable), never closed


def _bound():
    """Whether workers this process starts die with it: on Windows once it is in its own
    kill-on-close job (whose handle it never closes: closing it would end the engine too);
    on Linux through each worker's parent-death signal (:func:`serve`)."""
    global _JOB
    if sys.platform == "win32":
        if _JOB is None:
            _JOB = _kill_on_close_job()
        return bool(_JOB)
    return sys.platform.startswith("linux")


class _BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kill_on_close_job():
    """A new job holding this process, set to kill every process in it when its last handle
    closes; its handle (not inheritable), or 0 when Windows refuses any step."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.restype = ctypes.c_void_p
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    api.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    job = api.CreateJobObjectW(None, None)
    if not job:
        return 0
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    extended = 9  # JobObjectExtendedLimitInformation
    size = ctypes.sizeof(limits)
    if not api.SetInformationJobObject(job, extended, ctypes.byref(limits), size):
        api.CloseHandle(job)
        return 0
    if not api.AssignProcessToJobObject(job, api.GetCurrentProcess()):
        api.CloseHandle(job)  # still empty: closing it kills nothing
        return 0
    return job


class _Token:
    """Shapes exported together for workers: they keep their mutual sharing there."""

    def __init__(self, number, path, shapes):
        self.number, self.path = number, path
        self.shapes = shapes  # alive while workers compute on their copies
        self.loaded = set()  # workers holding this token's shapes


class _Call:
    """One pooled call: queued, sent, done, failed or cancelled."""

    def __init__(self, pool, number, token, message):
        self.pool, self.number, self.token, self.message = pool, number, token, message
        self.state, self.value = "queued", None


class _Worker:
    def __init__(self, conn):
        self.conn = conn
        self.inflight = {}  # call number -> _Call


def answer(call):
    """``call``'s answer (a tuple) once its worker has it, or None when the engine must
    compute it: no call, no worker has started it, or its worker failed or was lost."""
    return None if call is None else call.pool._take(call)


class Batch:
    """One loop's calls. :meth:`close` cancels the calls it did not take and frees its
    shapes in every worker; without a pool every call is the engine's own."""

    def __init__(self, pool):
        self.pool = pool
        self.tokens = {}  # shape ids -> _Token or None
        self.calls = []
        self.closers = []

    def submit(self, shapes, name, *args):
        """Queue engine function ``name(shapes, *args)``; the call, or None without a pool."""
        if self.pool is None or self.pool.broken:
            return None
        key = tuple(id(shape) for shape in shapes)
        if key not in self.tokens:
            self.tokens[key] = self.pool._share(shapes)
        call = self.pool._submit(self.tokens[key], name, args)
        if call is not None:
            self.calls.append(call)
        return call

    def on_close(self, closer):
        """Run ``closer()`` when the batch closes (callers forgetting their calls)."""
        self.closers.append(closer)

    def close(self):
        for closer in self.closers:
            closer()
        if self.pool is not None:
            self.pool._cancel(self.calls)
            for token in self.tokens.values():
                self.pool._release(token)
        self.tokens, self.calls, self.closers = {}, [], []


class Pool:
    """Up to ``size`` worker processes running ``command`` for one engine run, started
    with the first shared shapes; :meth:`close` stops them. ``answered`` counts the
    answers the engine took from them. A ``patient`` pool waits for a worker's answer to
    every call while some worker can still give it, so which calls a worker answered is
    deterministic (tests and audits); otherwise the engine computes a call no worker has
    started yet itself."""

    def __init__(self, size, command, patient=False, parent=None):
        self.size, self.command, self.patient = size, command, patient
        self.parent = parent  # where the pool's file directory goes (None: the temp dir)
        self.answered = 0
        self.directory = None
        self.listener = None
        self.processes = []
        self.workers = []
        self.joined = 0  # workers ever adopted
        self.arrived = []  # connections the accept thread admitted, not yet adopted
        self.lock = threading.Lock()
        self.queue = collections.deque()
        self.numbers = itertools.count()
        self.dropped = []  # released tokens workers may still hold
        self.broken = size < 1

    def close(self):
        """Stop every worker and remove the pool's files."""
        self.broken = True
        for worker in self.workers:
            try:
                worker.conn.send(("stop",))
                worker.conn.close()
            except Exception:
                pass
        if self.listener is not None:
            try:
                self.listener.close()
            except Exception:
                pass
        with self.lock:
            arrived, self.arrived = self.arrived, []
        for conn in arrived:
            conn.close()
        # Nothing a worker still computes or a starting one would do is needed any more.
        for process in self.processes:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(5)
            except Exception:
                pass
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
        self.workers, self.processes, self.queue = [], [], collections.deque()

    def _start(self):
        if self.directory is not None or self.broken:
            return
        if not _bound():
            self.broken = True  # a worker could outlive the engine: run every call here
            return
        try:
            self.directory = tempfile.mkdtemp(prefix="prechips-pool-", dir=self.parent)
            key = secrets.token_bytes(32)
            self.listener = Listener(authkey=key)
            environment = {**os.environ, KEY_ENV: key.hex(), PARENT_ENV: str(os.getpid())}
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for _ in range(self.size):
                self.processes.append(
                    subprocess.Popen(
                        [*self.command, "--pool", str(self.listener.address), self.directory],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=environment,
                        creationflags=flags,
                    )
                )
        except Exception:
            self.close()
            return
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        for _ in range(self.size):
            try:
                conn = self.listener.accept()
            except Exception:
                return
            with self.lock:
                self.arrived.append(conn)

    def _share(self, shapes):
        self._start()
        if self.broken:
            return None
        if any(face.countTriangles() for shape in shapes for face in shape.Faces):
            return None
        number = next(self.numbers)
        path = os.path.join(self.directory, f"s{number}.brp")
        try:
            Part.makeCompound(list(shapes)).exportBinary(path)
        except Exception:
            return None
        return _Token(number, path, list(shapes))

    def _release(self, token):
        if token is not None:
            token.shapes = None
            self.dropped.append(token)

    def _submit(self, token, name, args):
        if token is None or self.broken:
            return None
        number = next(self.numbers)
        call = _Call(self, number, token, ("call", number, name, token.number, args))
        self.queue.append(call)
        self._pump(False)
        return call

    def _take(self, call):
        self._pump(False)
        while call.state == "sent" or (call.state == "queued" and self.patient and self._alive()):
            self._pump(True)
        if call.state != "done":
            call.state = "cancelled"  # queued behind busy workers: the engine is quicker
            return None
        call.state = "cancelled"
        self.answered += 1
        return tuple(_decode(value) for value in call.value)

    def _cancel(self, calls):
        for call in calls:
            if call.state == "done":
                for value in call.value:
                    _discard(value)
            call.state = "cancelled"

    def _alive(self):
        """Whether a worker can still answer: one is connected or one is still starting."""
        if self.broken:
            return False
        if self.workers:
            return True
        starting = self.joined < len(self.processes)
        return starting and any(process.poll() is None for process in self.processes)

    def _pump(self, block):
        """Adopt arrived workers, send queued calls and collect answers; ``block`` waits up
        to a second for some busy worker to answer or fail."""
        with self.lock:
            arrived, self.arrived = self.arrived, []
        self.workers.extend(_Worker(conn) for conn in arrived)
        self.joined += len(arrived)
        self._dispatch()
        busy = [worker for worker in self.workers if worker.inflight]
        if not busy:
            if block:
                time.sleep(0.05)  # workers still starting
            return
        ready = wait([worker.conn for worker in busy], timeout=1.0 if block else 0)
        for worker in busy:
            if worker.conn in ready:
                self._receive(worker)
        self._dispatch()

    def _dispatch(self):
        for token in self.dropped:
            for worker in list(token.loaded):
                self._send(worker, ("drop", token.number))
            token.loaded.clear()
            try:
                os.remove(token.path)
            except OSError:
                pass
        self.dropped = []
        for worker in list(self.workers):
            while len(worker.inflight) < DEPTH and self.queue:
                call = self.queue.popleft()
                if call.state != "queued":
                    continue
                token = call.token
                if worker not in token.loaded:
                    if not self._send(worker, ("load", token.number, token.path)):
                        self.queue.appendleft(call)
                        break
                    token.loaded.add(worker)
                if not self._send(worker, call.message):
                    self.queue.appendleft(call)
                    break
                call.state = "sent"
                worker.inflight[call.number] = call

    def _send(self, worker, message):
        try:
            worker.conn.send(message)
        except Exception:
            self._lose(worker)
            return False
        return True

    def _receive(self, worker):
        try:
            number, ok, value = worker.conn.recv()
        except Exception:
            self._lose(worker)
            return
        call = worker.inflight.pop(number, None)
        if call is None or call.state == "cancelled":
            for item in value if ok else ():
                _discard(item)
            return
        call.state, call.value = ("done", value) if ok else ("failed", None)

    def _lose(self, worker):
        """A worker that cannot be reached: its calls fall back to the engine."""
        if worker not in self.workers:
            return
        self.workers.remove(worker)
        for call in worker.inflight.values():
            if call.state == "sent":
                call.state = "failed"
        worker.inflight.clear()
        try:
            worker.conn.close()
        except Exception:
            pass


def serve(address, directory, functions):
    """A worker's loop: load shared shapes and run calls on them until told to stop or
    the engine is gone. On Linux it first has the kernel kill it when the engine dies, and
    serves nothing when that cannot be set or the engine is already gone (its calls stay
    the engine's); on Windows the engine's job does the same."""
    if sys.platform.startswith("linux"):
        # The signal fires when the engine thread that started this worker ends; workers
        # start on the engine's main thread, so that is when the engine ends.
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, *[ctypes.c_ulong] * 4]
        if libc.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            return
        if os.getppid() != int(os.environ[PARENT_ENV]):  # the engine ended first
            return
    conn = Client(address, authkey=bytes.fromhex(os.environ[KEY_ENV]))
    shapes = {}
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            return
        kind = message[0]
        if kind == "stop":
            return
        if kind == "load":
            _, number, path = message
            try:
                compound = Part.Shape()
                compound.importBinary(path)
                shapes[number] = compound.childShapes()
            except Exception as exc:
                shapes[number] = exc
        elif kind == "drop":
            shapes.pop(message[1], None)
        elif kind == "call":
            _, number, name, token, args = message
            try:
                loaded = shapes[token]
                if isinstance(loaded, Exception):
                    raise loaded
                values = functions[name](loaded, *args)
                encoded = [_encode(directory, f"r{number}-{k}", v) for k, v in enumerate(values)]
                reply = (number, True, encoded)
            except Exception as exc:
                reply = (number, False, repr(exc))
            try:
                conn.send(reply)
            except (EOFError, OSError):
                return


def _encode(directory, name, value):
    if isinstance(value, Part.Shape):
        path = os.path.join(directory, name + ".brp")
        value.exportBinary(path)
        return ("shape", path)
    return ("value", value)


def _decode(value):
    kind, payload = value
    if kind != "shape":
        return payload
    shape = Part.Shape()
    shape.importBinary(payload)
    os.remove(payload)
    return shape


def _discard(value):
    if value[0] == "shape":
        try:
            os.remove(value[1])
        except OSError:
            pass
