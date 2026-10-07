"""Terminal output of the `zvt` CLI, built with rich."""
import contextlib
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ecrterm.common import INTERMEDIATE_STATUS_CODES
from ecrterm.conv import toHexString
from ecrterm.packets.base_packets import (
    IntermediateStatusInformation, PrintLine, PrintTextBlock,
    StatusInformation)


class Renderer(object):

    def __init__(self, console=None, json_mode=False, log_packets=False):
        # keep the real stdout: library prints are redirected while a
        # command runs, our own output must not be.
        self.console = console or Console(file=sys.stdout, highlight=False)
        self.json_mode = json_mode
        self.log_packets = log_packets
        encoding = (self.console.encoding or '').lower().replace('-', '')
        self.unicode = encoding.startswith('utf')

    def sym(self, fancy, plain):
        return fancy if self.unicode else plain

    # results
    #########################################################################

    def result(self, result):
        if self.json_mode:
            self._json(result.as_dict())
            return
        if result.receipt:
            self.console.print(Panel(
                Text('\n'.join(result.receipt)), title='Receipt',
                expand=False, border_style='cyan'))
        if result.rows:
            self.table(result.columns, result.rows)
        if result.message:
            style = 'bold green' if result.ok else 'bold red'
            mark = self.sym('✔', 'OK') if result.ok else self.sym(
                '✘', 'ERROR')
            self.console.print(Text('%s %s' % (mark, result.message), style))

    def table(self, columns, rows):
        table = Table(show_header=bool(columns), header_style='bold')
        for column in columns:
            table.add_column(column, overflow='fold')
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self.console.print(table)

    def _json(self, data):
        self.console.file.write(json.dumps(data, default=str) + '\n')
        self.console.file.flush()

    def error(self, message):
        if self.json_mode:
            self._json({'ok': False, 'message': message})
        else:
            mark = self.sym('✘', 'ERROR')
            self.console.print(Text('%s %s' % (mark, message), 'bold red'))

    def info(self, message, style='dim'):
        if not self.json_mode:
            self.console.print(Text(message, style))

    def confirm(self, question):
        if self.json_mode or not sys.stdin.isatty():
            return False
        try:
            answer = self.console.input('%s [y/N] ' % question)
        except EOFError:
            return False
        return answer.strip().lower() in ('y', 'yes', 'j', 'ja')

    # progress while a command runs
    #########################################################################

    @contextlib.contextmanager
    def progress(self, title):
        """Yield an `on_event` callback showing live PT status."""
        if self.json_mode:
            yield lambda event: None
            return
        with self.console.status(title, spinner='dots') as status:
            def on_event(event):
                self._event(event, status, title)
            yield on_event

    def _event(self, event, status, title):
        if event.kind == 'log':
            self._log(event.data, event.incoming)
        elif event.kind == 'output':
            if self.log_packets:
                self.console.print(Text(event.data, 'dim italic'))
        elif event.kind == 'packet':
            packet = event.packet
            if isinstance(packet, IntermediateStatusInformation):
                text = INTERMEDIATE_STATUS_CODES.get(
                    packet.fixed_values.get('intermediate_status'),
                    'unknown status')
                status.update('%s: [bold]%s[/bold]' % (title, text))
                self.console.print(Text('  - %s' % text, 'yellow'))
            elif isinstance(packet, (PrintLine, PrintTextBlock)):
                pass  # shown as receipt at the end.
            elif isinstance(packet, StatusInformation):
                info = ', '.join('%s=%s' % (b._key, b.value())
                                 for b in packet.bitmaps)
                self.console.print(Text('  - status information %s'
                                        % info, 'yellow'))

    def _log(self, data, incoming):
        try:
            hexdata = toHexString(list(data))
        except Exception:
            hexdata = repr(data)
        arrow = '<- PT ' if incoming else '-> PT '
        self.console.print(Text(arrow + hexdata,
                                'magenta' if incoming else 'blue'))

    def interrupted(self, count):
        if count == 1:
            self.info('Abort requested (honoured only while the PT shows '
                      '"insert card"). Press Ctrl+C again to disconnect.',
                      'bold yellow')
        else:
            self.info('Disconnected.', 'bold red')
