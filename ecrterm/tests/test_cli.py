"""
Tests for the simulator transport and the `zvt` CLI. CLI tests are skipped when
the `cli` extra (rich, prompt_toolkit) is not installed.
"""
import _thread
import argparse
import configparser
import io
import json
import threading
from contextlib import redirect_stdout
from unittest import TestCase, main, skipIf

from ecrterm.ecr import ECR
from ecrterm.packets.base_packets import Abort, Registration

try:
    from rich.console import Console
    import prompt_toolkit  # noqa: F401
    HAS_CLI = True
except ImportError:
    HAS_CLI = False


class TestSimulatorTransport(TestCase):

    def test_payment_approved(self):
        ecr = ECR('simulator://')
        self.assertTrue(ecr.payment(amount_cent=150))
        self.assertIn('Zahlung erfolgt', ecr.last_printout())

    def test_payment_declined(self):
        ecr = ECR('simulator://')
        self.assertFalse(ecr.payment(amount_cent=199))
        self.assertIsInstance(ecr.transmitter.last.completion, Abort)
        ecr = ECR('simulator://?scenario=decline')
        self.assertFalse(ecr.payment(amount_cent=100))

    def test_status_and_registration(self):
        ecr = ECR('simulator://')
        self.assertEqual(0, ecr.register(Registration.generate_config()))
        self.assertEqual(0, ecr.status())
        self.assertEqual('SIMULATOR 1.0', ecr.version)

    def test_end_of_day_and_diagnosis(self):
        ecr = ECR('simulator://')
        self.assertEqual(0, ecr.end_of_day())
        self.assertIn('Tagesabschluss', ecr.daylog)
        self.assertEqual(0, ecr.diagnosis())
        self.assertIn('Diagnose', ecr.last_printout())

    def test_unknown_device(self):
        self.assertRaises(ValueError, ECR, 'foo')


@skipIf(not HAS_CLI, 'cli extra not installed')
class TestOneShot(TestCase):

    def zvt(self, *argv):
        from ecrterm.cli.main import main as zvt_main
        out = io.StringIO()
        with redirect_stdout(out):
            code = zvt_main(list(argv))
        return code, out.getvalue()

    def test_pay_approved(self):
        code, out = self.zvt('--device', 'simulator://', 'pay', '1,50')
        self.assertEqual(0, code)
        self.assertIn('Payment approved: 1,50 EUR', out)
        self.assertIn('Zahlung erfolgt', out)

    def test_pay_declined_json(self):
        code, out = self.zvt('-d', 'simulator://', '--json', 'pay', '--cents',
                             '199')
        self.assertEqual(1, code)
        data = json.loads(out)
        self.assertFalse(data['ok'])
        self.assertEqual(5, data['error_code'])
        self.assertEqual(199, data['amount_cent'])

    def test_status_json(self):
        code, out = self.zvt('-d', 'simulator://', '--json', 'status')
        self.assertEqual(0, code)
        self.assertEqual(0, json.loads(out)['terminal_status'])

    def test_usage_errors(self):
        self.assertEqual(2, self.zvt('-d', 'simulator://', 'pay')[0])
        self.assertEqual(2, self.zvt('-d', 'foo', 'status')[0])
        self.assertEqual(2, self.zvt('-d', 'simulator://', 'restart')[0])
        with redirect_stdout(io.StringIO()):
            self.assertRaises(SystemExit, self.zvt, 'pay', 'abc')

    def test_decode_is_offline(self):
        code, out = self.zvt('decode', '06 0F', '00')
        self.assertEqual(0, code)
        self.assertIn('Completion', out)

    def test_parse_amount(self):
        from ecrterm.cli.commands import parse_amount
        self.assertEqual(150, parse_amount('1,50'))
        self.assertEqual(100, parse_amount('1'))
        for bad in ('0', '-1', '1.001', 'x'):
            self.assertRaises(argparse.ArgumentTypeError, parse_amount, bad)


@skipIf(not HAS_CLI, 'cli extra not installed')
class TestSession(TestCase):

    def setUp(self):
        from ecrterm.cli.render import Renderer
        from ecrterm.cli.session import ZvtSession
        self.out = io.StringIO()
        self.renderer = Renderer(console=Console(file=self.out, width=120))
        self.session = ZvtSession(device='simulator://?delay=0.05')
        self.session.connect()

    def tearDown(self):
        self.session.disconnect()

    def test_ctrl_c_aborts_payment(self):
        from ecrterm.cli import commands
        cmd = commands.find('pay')
        args = cmd.parser.parse_args(['5'])
        interrupted = []

        def on_event(event):
            # interrupt the main thread on the first "insert card".
            if not interrupted:
                interrupted.append(True)
                threading.Timer(0.01, _thread.interrupt_main).start()

        result = self.session.execute(cmd, args, on_event=on_event)
        self.assertFalse(result.ok)
        self.assertEqual(1, result.exit_code)
        self.assertEqual(0x6C, result.data['error_code'])

    def test_repl_handle(self):
        from ecrterm.cli.repl import Repl
        repl = Repl(self.session, self.renderer)
        self.assertTrue(repl.handle('/status'))
        self.assertTrue(repl.handle('pay 2'))
        self.assertTrue(repl.handle('/nonsense'))
        self.assertTrue(repl.handle('/history -n 2'))
        self.assertTrue(repl.handle('/disconnect'))
        self.assertTrue(repl.handle('/status'))
        self.assertFalse(repl.handle('/quit'))
        out = self.out.getvalue()
        self.assertIn('PT ready', out)
        self.assertIn('Payment approved: 2,00 EUR', out)
        self.assertIn("Unknown command 'nonsense'", out)
        self.assertIn('Not connected', out)

    def test_completer(self):
        from prompt_toolkit.document import Document
        from ecrterm.cli.repl import ZvtCompleter
        words = [c.text for c in ZvtCompleter().get_completions(
            Document('/di'), None)]
        self.assertEqual(['/diag', '/disconnect', '/display'], words)
        words = [c.text for c in ZvtCompleter().get_completions(
            Document('/diag e'), None)]
        self.assertEqual(['emv', 'ep2', 'extended'], sorted(words))


@skipIf(not HAS_CLI, 'cli extra not installed')
class TestConfig(TestCase):

    def test_resolve_order(self):
        from ecrterm.cli import config
        parser = configparser.ConfigParser()
        parser.read_string('[default]\nprofile = shop\n'
                           '[shop]\ndevice = socket://1.2.3.4:20007\n'
                           'password = 111111\n')
        settings = config.resolve(env={}, parser=parser)
        self.assertEqual('socket://1.2.3.4:20007', settings['device'])
        self.assertEqual('111111', settings['password'])
        settings = config.resolve(env={'ZVT_DEVICE': 'simulator://'},
                                  parser=parser)
        self.assertEqual('simulator://', settings['device'])
        settings = config.resolve(device='COM3', env={}, parser=parser)
        self.assertEqual('COM3', settings['device'])
        self.assertRaises(KeyError, config.resolve, profile='nope', env={},
                          parser=parser)


if __name__ == '__main__':
    main()
