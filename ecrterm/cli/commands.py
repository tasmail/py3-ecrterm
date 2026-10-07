"""
Commands of the `zvt` CLI.

Each command is defined once and used both as a one-shot subcommand
(`zvt pay 1.00`) and as a REPL slash command (`/pay 1.00`). Handlers only
wrap `ECR` methods and return a `Result`, they never print.
"""
import argparse
import sys
from decimal import Decimal, InvalidOperation

from ecrterm.common import ERRORCODES, TERMINAL_STATUS_CODES
from ecrterm.conv import toHexString
from ecrterm.ecr import parse_represented_data
from ecrterm.packets.apdu import Packets
from ecrterm.packets.base_packets import Abort, Diagnosis, Packet
from ecrterm.packets.bitmaps import BITMAPS
from ecrterm.cli.session import (
    EXIT_DECLINED, EXIT_TRANSPORT, EXIT_USAGE, Result)

COMMANDS = {}  # name -> Command, in definition order.
ALIASES = {}  # alias -> name

DIAGNOSIS_TYPES = {
    'line': Diagnosis.TYPE_LINE,
    'extended': Diagnosis.TYPE_EXTENDED,
    'config': Diagnosis.TYPE_CONFIGURATION,
    'emv': Diagnosis.TYPE_EMV_CONFIGURATION,
    'ep2': Diagnosis.TYPE_EP2_CONFIGURATION,
}


class Command(object):

    def __init__(self, name, handler, help, aliases=(), offline=False,
                 abortable=False, confirm=False, arguments=()):
        self.name = name
        self.handler = handler
        self.help = help
        self.aliases = tuple(aliases)
        self.offline = offline
        self.abortable = abortable
        # ask before running, unless --yes is given.
        self.confirm = confirm
        self.arguments = arguments
        self._parser = None

    def configure(self, parser):
        for args, kwargs in self.arguments:
            parser.add_argument(*args, **kwargs)

    @property
    def parser(self):
        """Standalone parser used by the REPL."""
        if self._parser is None:
            self._parser = argparse.ArgumentParser(
                prog='/' + self.name, description=self.help)
            self.configure(self._parser)
        return self._parser


def arg(*args, **kwargs):
    return args, kwargs


def command(name, help, **kwargs):
    def decorator(handler):
        cmd = Command(name, handler, help, **kwargs)
        COMMANDS[name] = cmd
        for alias in cmd.aliases:
            ALIASES[alias] = name
        return handler
    return decorator


def find(name):
    name = name.lstrip('/').lower()
    return COMMANDS.get(ALIASES.get(name, name))


def parse_amount(text):
    """'1', '1.50' or '1,50' euros -> cents."""
    try:
        value = Decimal(text.replace(',', '.'))
    except InvalidOperation:
        raise argparse.ArgumentTypeError('invalid amount: %r' % text)
    cents = value * 100
    if value <= 0 or cents != cents.to_integral_value():
        raise argparse.ArgumentTypeError('invalid amount: %r' % text)
    return int(cents)


def format_cents(cents):
    return '%d,%02d EUR' % divmod(cents, 100)


def describe_error(code):
    text = ERRORCODES.get(code)
    if text is None and 0x01 <= code <= 0x63:
        text = 'error from network operator / authorisation system'
    return '0x%02X %s' % (code, (text or 'unknown error').strip())


def last_abort(ecr):
    for incoming, packet in reversed(ecr.transmitter.last_history):
        if incoming and isinstance(packet, Abort):
            return packet


def join_hex(words):
    """'06 0F', '00' -> '060F00' (the library only parses packed hex)."""
    return ''.join(''.join(words).replace(':', '').split())


def history_rows(history):
    return [['PT -> ECR' if incoming else 'ECR -> PT', repr(packet)]
            for incoming, packet in history]


# transactions
#############################################################################

@command('register', 'Register the ECR at the PT (done after connect).',
         arguments=[arg('--unlocked', action='store_true',
                        help='do not lock the PT admin menu (testing only)')])
def cmd_register(session, args):
    session.register(unlocked=args.unlocked)
    if not session.registered:
        return Result(ok=False, message='Registration failed.',
                      exit_code=EXIT_TRANSPORT)
    tid = session.ecr.terminal_id
    return Result(message='Registered%s.' % (' (TID %s)' % tid if tid else ''),
                  data={'terminal_id': tid})


@command('pay', 'Authorise a payment. Ctrl+C aborts while PT asks for card.',
         aliases=('payment',), abortable=True,
         arguments=[
             arg('amount', nargs='?', type=parse_amount,
                 help='amount in euros, e.g. 1.50 or 1,50'),
             arg('--cents', type=int, help='amount in cents instead')])
def cmd_pay(session, args):
    cents = args.cents if args.cents is not None else args.amount
    if not cents or cents <= 0:
        return Result(ok=False, message='Give an amount: pay 1.50',
                      exit_code=EXIT_USAGE)
    ecr = session.require_ecr()
    approved = ecr.payment(amount_cent=cents, listener=session.listener)
    data = {'amount_cent': cents}
    receipt = ecr.last_printout()
    if approved:
        return Result(message='Payment approved: %s' % format_cents(cents),
                      receipt=receipt, data=data)
    abort = last_abort(ecr)
    if abort is not None:
        data['error_code'] = abort.error_code
        message = 'Payment aborted: %s' % describe_error(abort.error_code)
    else:
        message = 'Payment not completed.'
    return Result(ok=False, message=message, receipt=receipt, data=data,
                  exit_code=EXIT_DECLINED)


@command('abort', 'Request abort of a running payment (same as Ctrl+C).')
def cmd_abort(session, args):
    session.require_ecr().abort_command()
    return Result(message='Abort requested, honoured only while the PT '
                          'shows "insert card".')


@command('eod', 'End of day (Tagesabschluss).', aliases=('end-of-day',))
def cmd_eod(session, args):
    ecr = session.require_ecr()
    ret = ecr.end_of_day(listener=session.listener)
    ok = ret == 0 and last_abort(ecr) is None
    return Result(ok=ok, message='End of day %s.' % (
        'done' if ok else 'failed'), receipt=list(ecr.daylog or []),
        exit_code=0 if ok else EXIT_DECLINED)


@command('diag', 'Diagnosis (06 70).', aliases=('diagnosis',),
         arguments=[arg('type', nargs='?', choices=sorted(DIAGNOSIS_TYPES),
                        help='diagnosis type, default: line diagnosis')])
def cmd_diag(session, args):
    ecr = session.require_ecr()
    ret = ecr.diagnosis(diagnosis_type=DIAGNOSIS_TYPES.get(args.type),
                        listener=session.listener)
    ok = ret == 0 and last_abort(ecr) is None
    return Result(ok=ok, message='Diagnosis %s.' % (
        'done' if ok else 'failed'),
                  receipt=ecr.last_printout(),
                  exit_code=0 if ok else EXIT_DECLINED)


@command('service-mode', 'Switch the PT into service mode.')
def cmd_service_mode(session, args):
    session.require_ecr().activate_service_mode(listener=session.listener)
    return Result(message='Service mode requested.')


# status
#############################################################################

def _status(session):
    status = session.require_ecr().status()
    session.last_status = status
    if status is False or status is None:
        return None, 'No status received.'
    return status, TERMINAL_STATUS_CODES.get(
        status, 'Unknown status 0x%02X' % status)


@command('status', 'Status enquiry (05 01).')
def cmd_status(session, args):
    status, text = _status(session)
    data = {'terminal_status': status, 'sw_version': session.ecr.version}
    if status is None:
        return Result(ok=False, message=text, exit_code=EXIT_TRANSPORT)
    return Result(message='%s (0x%02X), software %s' % (
        text, status, session.ecr.version), data=data)


@command('wait', 'Poll the status until the PT is ready.',
         arguments=[arg('--interval', type=float, default=2.0)])
def cmd_wait(session, args):
    while True:
        status, text = _status(session)
        if status is None:
            return Result(ok=False, message=text, exit_code=EXIT_TRANSPORT)
        if status == 0:
            return Result(message=text, data={'terminal_status': 0})
        print('%s (0x%02X)' % (text, status))
        if session.cancel.wait(args.interval):
            return Result(ok=False, message='Cancelled.',
                          exit_code=EXIT_DECLINED)


# display and printing
#############################################################################

@command('display', 'Show text on the PT display (max 4 lines).',
         arguments=[arg('lines', nargs='+', help='one argument per line'),
                    arg('--duration', type=int, default=5,
                        help='seconds, 0 = forever'),
                    arg('--beeps', type=int, default=0)])
def cmd_display(session, args):
    session.require_ecr().show_text(
        lines=args.lines, duration=args.duration, beeps=args.beeps)
    return Result(message='Text displayed.')


@command('print', 'Print a text file (or - for stdin) on the PT printer.',
         arguments=[arg('file', help='text file, - for stdin')])
def cmd_print(session, args):
    if args.file == '-':
        lines = sys.stdin.read().splitlines()
    else:
        with open(args.file, encoding='utf-8') as f:
            lines = f.read().splitlines()
    ret = session.require_ecr().print_text(
        lines=[(line, 0) for line in lines])
    return Result(ok=ret == 0, message='Printed %d lines.' % len(lines),
                  exit_code=0 if ret == 0 else EXIT_TRANSPORT)


@command('receipt', 'Show the receipt of the last command again.')
def cmd_receipt(session, args):
    receipt = session.require_ecr().last_printout()
    return Result(message='' if receipt else 'No receipt.', receipt=receipt)


# terminal control
#############################################################################

_yes = arg('--yes', '-y', action='store_true', help='do not ask')


@command('restart', 'Restart the PT (06 18).', confirm=True,
         arguments=[_yes])
def cmd_restart(session, args):
    session.require_ecr().restart()
    session.registered = False
    return Result(message='PT restarted. Register again with /register.')


@command('reset', 'Reset the transport and restart the PT.', confirm=True,
         arguments=[_yes])
def cmd_reset(session, args):
    session.require_ecr().reset()
    session.registered = False
    return Result(message='Transport reset and PT restarted.')


# expert / developer
#############################################################################

@command('history', 'Packets sent and received in this session.',
         arguments=[arg('-n', type=int, default=20, help='last N packets')])
def cmd_history(session, args):
    history = session.require_ecr().transmitter.history
    return Result(columns=['direction', 'packet'],
                  rows=history_rows(history[-args.n:]))


@command('send', 'Send a raw packet given as hex, e.g. "05 01 03 12 34 56".',
         arguments=[arg('hex', nargs='+')])
def cmd_send(session, args):
    packet = parse_represented_data(join_hex(args.hex))
    if not isinstance(packet, Packet):
        return Result(ok=False, message='Not a known packet: %r' % packet,
                      exit_code=EXIT_USAGE)
    packet.register_response_listener(session.listener)
    ecr = session.require_ecr()
    ecr.transmit(packet)
    return Result(columns=['direction', 'packet'],
                  rows=history_rows(ecr.transmitter.last_history))


def _printable(value):
    text = str(value)
    return text if text.isprintable() else repr(value)


@command('decode', 'Decode a packet given as hex (offline).', offline=True,
         arguments=[arg('hex', nargs='+')])
def cmd_decode(session, args):
    try:
        packet = parse_represented_data(join_hex(args.hex))
    except Exception as exc:
        return Result(ok=False, message='Cannot decode: %s' % exc,
                      exit_code=EXIT_USAGE)
    if packet is None:
        return Result(ok=False, message='Unknown packet.',
                      exit_code=EXIT_USAGE)
    if not isinstance(packet, Packet):
        return Result(message=str(packet))
    rows = [['class', packet.__class__.__name__],
            ['command', toHexString([packet.cmd_class, packet.cmd_instr])]]
    rows += [[str(k), _printable(v)] for k, v in packet.fixed_values.items()]
    rows += [['bmp %s' % b._key, _printable(b.value())]
             for b in packet.bitmaps]
    return Result(message=repr(packet), columns=['field', 'value'], rows=rows)


@command('packets', 'List the known packet classes (offline).', offline=True)
def cmd_packets(session, args):
    rows = sorted([key, cls.__name__, (cls.__doc__ or '').strip()
                   .split('\n')[0]] for key, cls in Packets.packets.items())
    return Result(columns=['command', 'class', 'description'], rows=rows)


@command('bitmaps', 'List the known ZVT bitmaps (offline).', offline=True)
def cmd_bitmaps(session, args):
    rows = [['0x%02X' % key, name, descr]
            for key, (_, name, descr) in sorted(BITMAPS.items())]
    return Result(columns=['bitmap', 'name', 'description'], rows=rows)
