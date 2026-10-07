"""
In-process payment terminal simulator, selected with a `simulator://`
device URI.

It answers every ECR packet with a scripted sequence of PT packets, so the
ECR/CLI can be used and tested without hardware. The responses are built as
raw APDU bytes and parsed with `APDUPacket.parse`, exactly like the socket
transport does.

URI options: `simulator://?scenario=approve|decline&delay=0.5&tid=52500038`
- scenario: `approve` (default) or `decline`. A payment whose amount ends
  in 99 cents is always declined.
- delay: seconds to wait before each incoming packet (default 0).
- tid: terminal id returned on registration (8 digits).
"""
import time
from collections import deque

try:
    from urllib.parse import parse_qs, urlsplit
except ImportError:
    from urlparse import urlparse, parse_qs
    urlsplit = urlparse

from ecrterm.common import Transport, noop
from ecrterm.conv import toHexString
from ecrterm.exceptions import TransportLayerException
from ecrterm.packets.apdu import APDUPacket

ACK_PACKET = [0x80, 0x00, 0x00]
EMPTY_COMPLETION = [0x06, 0x0F, 0x00]
ERROR_DECLINED = 0x05
ERROR_ABORTED = 0x6C
INSERT_CARD_REPEATS = 5


def _apdu(cmd_class, cmd_instr, data=None):
    data = list(data or [])
    return [cmd_class, cmd_instr, len(data)] + data


def _bcd(number, length):
    digits = str(number).rjust(length * 2, '0')
    return [int(digits[i:i + 2], 16) for i in range(0, len(digits), 2)]


def _lllvar(text):
    raw = list(bytearray(text.encode('ascii')))
    length = '%03d' % len(raw)
    return [0xF0 | int(digit) for digit in length] + raw


def _print_line(text):
    return _apdu(0x06, 0xD1, [0x00] + list(bytearray(text.encode('cp437'))))


def _intermediate_status(code):
    return _apdu(0x04, 0xFF, [code])


def _abort(error_code):
    return _apdu(0x06, 0x1E, [error_code])


class SimulatorTransport(Transport):
    insert_delays = False
    slog = noop
    sw_version = 'SIMULATOR 1.0'

    def __init__(self, uri='simulator://'):
        query = parse_qs(urlsplit(uri).query)
        self.scenario = query.get('scenario', ['approve'])[0]
        self.delay = float(query.get('delay', ['0'])[0])
        self.tid = int(query.get('tid', ['52500038'])[0])
        self.receipt_number = 1
        self.queue = deque()
        self.connected = False

    def connect(self, *args, **kwargs):
        self.connected = True
        return True

    def close(self):
        self.connected = False

    def reset(self):
        self.queue.clear()

    def send(self, apdu, tries=0, no_wait=False):
        data = apdu.to_list()
        self.slog(data=data, incoming=False)
        if (data[0], data[1]) == (0x80, 0x00):
            # PacketReceived from the ECR: nothing to answer.
            return True
        responses = self.respond(data)
        first = responses.pop(0)
        self.queue.extend(responses)
        if no_wait:
            return True
        return True, self._parse(first)

    def receive(self, timeout=None, *args, **kwargs):
        if not self.queue:
            raise TransportLayerException('simulator: no more data.')
        if self.delay:
            time.sleep(self.delay)
        return True, self._parse(self.queue.popleft())

    def _parse(self, data):
        self.slog(data=data, incoming=True)
        return APDUPacket.parse(blob=data)

    # scenarios
    #########################################################################

    def respond(self, data):
        """Return the list of raw packets the PT sends for `data`."""
        command = (data[0], data[1])
        if command == (0x06, 0x00):
            return [ACK_PACKET, _apdu(0x06, 0x0F, [0x29] + _bcd(self.tid, 4))]
        if command == (0x05, 0x01):
            return [ACK_PACKET, _apdu(
                0x06, 0x0F, _lllvar(self.sw_version) + [0x00])]
        if command == (0x06, 0x01):
            return self.respond_payment(data)
        if command == (0x06, 0xB0):
            # AbortCommand: the running payment is cancelled.
            self.queue.clear()
            return [_abort(ERROR_ABORTED)]
        if command == (0x06, 0x50):
            return [ACK_PACKET, _apdu(0x04, 0x0F, [0x27, 0x00])] + [
                _print_line(line) for line in self.receipt(
                    'Tagesabschluss', ['Summe Buchungen:      %d' % (
                        self.receipt_number - 1)])
            ] + [EMPTY_COMPLETION]
        if command == (0x06, 0x70):
            return [ACK_PACKET] + [
                _print_line(line) for line in self.receipt(
                    'Diagnose', ['Verbindung:            OK'])
            ] + [EMPTY_COMPLETION]
        packet = APDUPacket.parse(blob=data)
        if getattr(packet, 'wait_for_completion', False):
            return [ACK_PACKET, EMPTY_COMPLETION]
        return [ACK_PACKET]

    def respond_payment(self, data):
        packet = APDUPacket.parse(blob=data)
        bitmaps = dict((b._key, b) for b in packet.bitmaps)
        amount = int(bitmaps['amount'].value()) if 'amount' in bitmaps else 0
        responses = [ACK_PACKET]
        responses += [_intermediate_status(0x0A)] * INSERT_CARD_REPEATS
        responses += [_intermediate_status(0x01),
                      _intermediate_status(0x04)]
        if self.scenario == 'decline' or amount % 100 == 99:
            responses += [_intermediate_status(0x13)]
            responses += [_print_line(line) for line in self.receipt(
                'Zahlung', ['Betrag:  %s EUR' % _euro(amount),
                            'Zahlung nicht moeglich'])]
            return responses + [_abort(ERROR_DECLINED)]
        responses += [_apdu(0x04, 0x0F, [0x27, 0x00, 0x04] + _bcd(amount, 6))]
        responses += [_print_line(line) for line in self.receipt(
            'Zahlung', ['Betrag:  %s EUR' % _euro(amount),
                        'Beleg-Nr.: %04d' % self.receipt_number,
                        'Zahlung erfolgt'])]
        self.receipt_number += 1
        return responses + [EMPTY_COMPLETION]

    def receipt(self, title, lines):
        return ['*** SIMULATOR ***', title, 'TID: %08d' % self.tid,
                time.strftime('%d.%m.%Y %H:%M')] + lines + ['']

    def __repr__(self):
        return 'SimulatorTransport(%s, queued=%s)' % (
            self.scenario, [toHexString(p[:2]) for p in self.queue])


def _euro(amount_cent):
    return ('%d,%02d' % divmod(amount_cent, 100))
