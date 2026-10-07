"""Interactive `zvt` session built with prompt_toolkit."""
import os
import shlex
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory, InMemoryHistory

from ecrterm import __version__
from ecrterm.cli import commands as cli_commands
from ecrterm.cli import config
from ecrterm.cli.main import connect, run_command
from ecrterm.cli.session import EXIT_OK, NotConnected
from ecrterm.common import TERMINAL_STATUS_CODES

BUILTINS = {
    'help': 'Show this help, or /help COMMAND for its options.',
    'connect': 'Connect to a PT: /connect socket://host:20007, COM3 or '
               'simulator://',
    'disconnect': 'Close the connection to the PT.',
    'clear': 'Clear the screen.',
    'exit': 'Leave the session (also quit or Ctrl+D).',
}
BUILTIN_ALIASES = {'quit': 'exit', '?': 'help', 'h': 'help'}


class ZvtCompleter(Completer):

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        words = text.split()
        if len(words) <= 1 and not text.endswith(' '):
            prefix = text.lstrip('/')
            slash = '/' if text.startswith('/') else ''
            names = sorted(list(BUILTINS) + list(cli_commands.COMMANDS))
            for name in names:
                if name.startswith(prefix):
                    meta = BUILTINS.get(name) or cli_commands.COMMANDS[
                        name].help
                    yield Completion(slash + name, start_position=-len(text),
                                     display_meta=meta)
            return
        cmd = cli_commands.find(words[0])
        if cmd is None:
            return
        current = '' if text.endswith(' ') else words[-1]
        candidates = []
        for action in cmd.parser._actions:
            candidates += [o for o in action.option_strings
                           if o.startswith('--')]
            if action.choices and not action.option_strings:
                candidates += list(action.choices)
        for candidate in candidates:
            if candidate.startswith(current):
                yield Completion(candidate, start_position=-len(current))


class Repl(object):

    def __init__(self, session, renderer):
        self.session = session
        self.renderer = renderer
        self.console = renderer.console

    def run(self):
        self.banner()
        if self.session.device:
            result = connect(self.session, self.renderer)
            self.renderer.result(result)
        read_line = self._line_reader()
        try:
            while True:
                try:
                    line = read_line()
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
                if not self.handle(line):
                    break
        finally:
            self.session.disconnect()
        return EXIT_OK

    def _line_reader(self):
        """
        prompt_toolkit needs a real console. For piped input (scripts) or
        terminals it cannot drive (mintty without winpty) fall back to
        plain `input()`.
        """
        if sys.stdin.isatty():
            try:
                prompt = PromptSession(
                    history=self._history(), completer=ZvtCompleter(),
                    complete_while_typing=True, bottom_toolbar=self.toolbar)
                return lambda: prompt.prompt(self.prompt_text)
            except Exception as exc:
                self.renderer.info('Line editing not available (%s), using '
                                   'plain input.' % exc.__class__.__name__)
        return lambda: input(self.prompt_text() if sys.stdin.isatty()
                             else '')

    def _history(self):
        path = config.history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return FileHistory(path)
        except OSError:
            return InMemoryHistory()

    def banner(self):
        self.console.print('[bold cyan]zvt[/bold cyan] py3-ecrterm %s, ZVT '
                           '700 terminal shell' % __version__)
        self.console.print('[dim]Type /help for commands, Tab to complete, '
                           'Ctrl+C aborts a running payment, Ctrl+D exits.'
                           '[/dim]')
        if not self.session.device:
            self.console.print('[yellow]No device configured, use /connect '
                               'socket://host:20007 or /connect simulator://'
                               '[/yellow]')

    def prompt_text(self):
        return 'zvt [%s] > ' % self.session.describe()

    def toolbar(self):
        s = self.session
        if not s.connected:
            return ' offline - /connect URI'
        status = s.last_status
        status_text = '-'
        if type(status) is int:
            status_text = TERMINAL_STATUS_CODES.get(status, '0x%02X' % status)
        return ' %s | %s | last status: %s' % (
            s.device, 'registered' if s.registered else 'not registered',
            status_text)

    # commands
    #########################################################################

    def handle(self, line):
        """Handle one input line, return False to leave the REPL."""
        try:
            words = shlex.split(line)
        except ValueError as exc:
            self.renderer.error(str(exc))
            return True
        if not words:
            return True
        name = words[0].lstrip('/').lower()
        name = BUILTIN_ALIASES.get(name, name)
        rest = words[1:]
        if name == 'exit':
            return False
        if name in BUILTINS:
            getattr(self, 'do_' + name)(rest)
            return True
        command = cli_commands.find(name)
        if command is None:
            self.renderer.error('Unknown command %r, try /help.' % name)
            return True
        try:
            args = command.parser.parse_args(rest)
        except SystemExit:  # argparse printed usage or help.
            return True
        if not command.offline and not self.session.connected:
            self.renderer.error('Not connected, use /connect first.')
            return True
        try:
            run_command(self.session, self.renderer, command, args)
        except NotConnected as exc:
            self.renderer.error(str(exc))
        return True

    def do_help(self, rest):
        if rest:
            command = cli_commands.find(rest[0])
            if command is None:
                self.renderer.error('Unknown command %r.' % rest[0])
            else:
                command.parser.print_help()
            return
        rows = [['/' + name, '', text] for name, text in BUILTINS.items()]
        rows += [['/' + cmd.name, ', '.join(cmd.aliases), cmd.help]
                 for cmd in cli_commands.COMMANDS.values()]
        self.renderer.table(['command', 'aliases', 'description'], rows)

    def do_connect(self, rest):
        if rest:
            self.session.device = rest[0]
        if not self.session.device:
            self.renderer.error('Usage: /connect socket://host:20007')
            return
        self.renderer.result(connect(self.session, self.renderer))

    def do_disconnect(self, rest):
        self.session.disconnect()
        self.renderer.info('Disconnected.')

    def do_clear(self, rest):
        self.console.clear()
