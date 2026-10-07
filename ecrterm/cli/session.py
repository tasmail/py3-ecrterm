"""
UI independent session state of the `zvt` CLI.

A `ZvtSession` owns the `ECR` and executes commands. Commands talking to the
PT run in a worker thread, because a transmission blocks until the PT gives
back master rights. Packets reported by the transmission (status, print
lines, packet log) are forwarded as events to the main thread, which keeps
handling Ctrl+C (abort) meanwhile.
"""
import contextlib
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ecrterm.ecr import ECR
from ecrterm.exceptions import ZVTException
from ecrterm.packets.base_packets import Registration

EXIT_OK = 0
EXIT_DECLINED = 1
EXIT_USAGE = 2
EXIT_TRANSPORT = 3


class NotConnected(Exception):
    """Raised when a command needs a PT but the session has none."""


@dataclass
class Result:
    ok: bool = True
    message: str = ''
    receipt: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[List[str]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    exit_code: int = EXIT_OK

    def as_dict(self):
        ret = {'ok': self.ok, 'message': self.message,
               'exit_code': self.exit_code}
        if self.receipt:
            ret['receipt'] = self.receipt
        if self.rows:
            ret['rows'] = [dict(zip(self.columns, row)) for row in self.rows]
        ret.update(self.data)
        return ret


@dataclass
class Event:
    """Something the PT or the library reported while a command runs."""
    kind: str  # 'packet' (PT packet), 'log' (raw data), 'output' (stdout)
    packet: Any = None
    incoming: bool = False
    data: Any = None


class _QueueWriter(object):
    """File like object putting library `print()` output on the queue."""

    def __init__(self, events):
        self.events = events

    def write(self, text):
        if text.strip():
            self.events.put(Event('output', data=text.rstrip()))
        return len(text)

    def flush(self):
        pass


class ZvtSession(object):

    def __init__(self, device=None, password='123456', profile=None,
                 auto_register=True, log_packets=False):
        self.device = device
        self.password = password
        self.profile = profile
        self.auto_register = auto_register
        self.log_packets = log_packets
        self.ecr = None
        self.registered = False
        self.last_status = None
        self.busy = False
        self.cancel = threading.Event()
        self._events = None  # queue of the running command.

    # connection
    #########################################################################

    @property
    def connected(self):
        return self.ecr is not None

    def connect(self, device=None):
        """Connect to `device` (or the configured one)."""
        self.disconnect()
        self.device = device or self.device
        if not self.device:
            raise NotConnected('No device given, use --device or a profile.')
        self.ecr = ECR(device=self.device, password=self.password)
        self.ecr.transport.slog = self._slog
        self.registered = False

    def disconnect(self):
        if self.ecr is not None:
            try:
                self.ecr.close()
            except Exception:
                pass
        self.ecr = None
        self.registered = False

    def require_ecr(self):
        if self.ecr is None:
            raise NotConnected('Not connected, use /connect first.')
        return self.ecr

    def register(self, unlocked=False):
        ecr = self.require_ecr()
        if unlocked:
            ret = ecr.register_unlocked()
        else:
            ret = ecr.register(config_byte=Registration.generate_config())
        self.registered = ret == 0
        return ret

    # event plumbing
    #########################################################################

    def emit(self, event):
        if self._events is not None:
            self._events.put(event)

    def listener(self, packet):
        """Response listener passed to the ECR methods."""
        self.emit(Event('packet', packet=packet, incoming=True))

    def _slog(self, data, incoming=False):
        if self.log_packets:
            self.emit(Event('log', data=data, incoming=incoming))

    # execution
    #########################################################################

    def execute(self, command, args, on_event=None, on_interrupt=None):
        """
        Execute `command` with parsed `args` and return its `Result`.

        Offline commands run directly. Commands talking to the PT run in a
        worker thread, `on_event(Event)` is called in the calling thread for
        everything reported meanwhile. The first Ctrl+C aborts the command
        (`on_interrupt(1)`), the second disconnects (`on_interrupt(2)`).
        """
        if command.offline:
            return command.handler(self, args)
        self.require_ecr()

        events = queue.Queue()
        outcome = {}

        def work():
            try:
                with contextlib.redirect_stdout(_QueueWriter(events)):
                    outcome['result'] = command.handler(self, args)
            except BaseException as exc:
                outcome['error'] = exc

        self.cancel.clear()
        self._events = events
        self.busy = True
        worker = threading.Thread(target=work, name='zvt-' + command.name)
        worker.daemon = True
        worker.start()
        interrupts = 0
        try:
            while worker.is_alive() or not events.empty():
                try:
                    event = events.get(timeout=0.1)
                except queue.Empty:
                    continue
                except KeyboardInterrupt:
                    interrupts += 1
                    if interrupts == 1:
                        self.cancel.set()
                        if command.abortable and self.ecr is not None:
                            self.ecr.abort_command()
                    else:
                        self.disconnect()
                    if on_interrupt:
                        on_interrupt(interrupts)
                    if interrupts > 1:
                        return Result(
                            ok=False, message='Interrupted, disconnected.',
                            exit_code=EXIT_TRANSPORT)
                    continue
                if on_event:
                    on_event(event)
        finally:
            self._events = None
            self.busy = False

        if 'error' in outcome:
            return self._error_result(outcome['error'])
        return outcome.get('result') or Result()

    def _error_result(self, exc):
        if isinstance(exc, NotConnected):
            return Result(ok=False, message=str(exc), exit_code=EXIT_USAGE)
        if isinstance(exc, (ZVTException, OSError)):
            return Result(ok=False, message='%s: %s' % (
                exc.__class__.__name__, exc), exit_code=EXIT_TRANSPORT)
        if isinstance(exc, KeyboardInterrupt):
            return Result(ok=False, message='Interrupted.',
                          exit_code=EXIT_TRANSPORT)
        raise exc

    # helpers for the prompt / toolbar
    #########################################################################

    def describe(self):
        parts = []
        if self.profile:
            parts.append(self.profile)
        if self.device:
            parts.append(self.device.replace('socket://', ''))
        if self.ecr is not None and self.ecr.terminal_id:
            parts.append('TID %s' % self.ecr.terminal_id)
        if self.ecr is None:
            parts.append('offline')
        return ' | '.join(parts)
