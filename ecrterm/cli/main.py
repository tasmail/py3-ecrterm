"""
Entry point of the `zvt` CLI.

    zvt --device socket://192.168.1.10:20007          # interactive REPL
    zvt --device socket://192.168.1.10:20007 pay 1.50 # one-shot command
    zvt --device simulator:// status                  # terminal simulator
"""
import argparse
import sys

from ecrterm import __version__
from ecrterm.cli import commands as cli_commands
from ecrterm.cli import config
from ecrterm.cli.session import (
    EXIT_OK, EXIT_TRANSPORT, EXIT_USAGE, NotConnected, Result, ZvtSession)
from ecrterm.exceptions import ZVTException


def build_parser():
    parser = argparse.ArgumentParser(
        prog='zvt', description='ZVT 700 payment terminal CLI. Without a '
        'command an interactive session is started.')
    parser.add_argument('--version', action='version',
                        version='py3-ecrterm %s' % __version__)
    parser.add_argument('--device', '-d', help='COM3, /dev/ttyUSB0, '
                        'socket://host:20007 or simulator:// (env ZVT_DEVICE)')
    parser.add_argument('--password', help='PT password (env ZVT_PASSWORD)')
    parser.add_argument('--profile', '-p', help='profile from %s'
                        % config.config_path())
    parser.add_argument('--log-packets', action='store_true',
                        help='show every packet sent and received')
    parser.add_argument('--json', action='store_true',
                        help='machine readable output (one-shot only)')
    parser.add_argument('--no-register', action='store_true',
                        help='do not register at the PT after connecting')
    sub = parser.add_subparsers(dest='command', metavar='command')
    for cmd in cli_commands.COMMANDS.values():
        cmd.configure(sub.add_parser(cmd.name, aliases=list(cmd.aliases),
                                     help=cmd.help, description=cmd.help))
    return parser


def connect(session, renderer):
    """Connect (and register) the session, return a `Result`."""
    try:
        session.connect()
    except (NotConnected, ValueError) as exc:
        return Result(ok=False, message=str(exc), exit_code=EXIT_USAGE)
    except (ZVTException, OSError) as exc:
        return Result(ok=False, message='Cannot connect to %s: %s' % (
            session.device, exc), exit_code=EXIT_TRANSPORT)
    if session.auto_register:
        return run_command(session, renderer,
                           cli_commands.find('register'),
                           argparse.Namespace(unlocked=False), show=False)
    return Result(message='Connected.')


def run_command(session, renderer, command, args, show=True):
    """Execute a command with live progress and print its result."""
    if command.confirm and not getattr(args, 'yes', False):
        if not renderer.confirm('Really %s the PT?' % command.name):
            result = Result(ok=False, message='Cancelled.',
                            exit_code=EXIT_USAGE)
            renderer.result(result)
            return result
    with renderer.progress('%s ...' % command.name) as on_event:
        result = session.execute(command, args, on_event=on_event,
                                 on_interrupt=renderer.interrupted)
    if show or not result.ok:
        renderer.result(result)
    return result


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        from ecrterm.cli.render import Renderer
    except ImportError:
        sys.stderr.write('The zvt CLI needs extra packages: '
                         'pip install py3-ecrterm[cli]\n')
        return EXIT_USAGE

    renderer = Renderer(json_mode=args.json and bool(args.command),
                        log_packets=args.log_packets)
    try:
        settings = config.resolve(device=args.device, password=args.password,
                                  profile=args.profile)
    except KeyError as exc:
        renderer.error(exc.args[0])
        return EXIT_USAGE
    session = ZvtSession(auto_register=not args.no_register,
                         log_packets=args.log_packets, **settings)

    if not args.command:
        from ecrterm.cli.repl import Repl
        return Repl(session, renderer).run()

    command = cli_commands.find(args.command)
    try:
        if not command.offline:
            result = connect(session, renderer)
            if not result.ok:
                renderer.result(result)
                return result.exit_code
        return run_command(session, renderer, command, args).exit_code
    finally:
        session.disconnect()


def run():
    sys.exit(main() or EXIT_OK)


if __name__ == '__main__':
    run()
