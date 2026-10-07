"""
Settings of the `zvt` CLI.

Resolution order: command line > environment (ZVT_DEVICE, ZVT_PASSWORD,
ZVT_PROFILE) > profile in the config file > defaults.

The config file is `%APPDATA%\\zvt\\config.ini` on Windows and
`~/.config/zvt/config.ini` elsewhere (override with ZVT_CONFIG)::

    [default]
    profile = shop1

    [shop1]
    device = socket://172.30.1.64:20007
    password = 123456
"""
import configparser
import os
import sys

DEFAULT_PASSWORD = '123456'


def config_dir():
    if sys.platform == 'win32' and os.environ.get('APPDATA'):
        return os.path.join(os.environ['APPDATA'], 'zvt')
    return os.path.join(os.path.expanduser('~'), '.config', 'zvt')


def config_path():
    return os.environ.get('ZVT_CONFIG') or os.path.join(
        config_dir(), 'config.ini')


def history_path():
    return os.path.join(config_dir(), 'history')


def load(path=None):
    parser = configparser.ConfigParser()
    parser.read(path or config_path(), encoding='utf-8')
    return parser


def resolve(device=None, password=None, profile=None, env=None, parser=None):
    """Return a dict with `device`, `password` and `profile`."""
    env = os.environ if env is None else env
    parser = load() if parser is None else parser
    profile = profile or env.get('ZVT_PROFILE') or parser.get(
        'default', 'profile', fallback=None)
    section = {}
    if profile:
        if not parser.has_section(profile):
            raise KeyError('Unknown profile %r in %s' % (
                profile, config_path()))
        section = parser[profile]
    return {
        'device': device or env.get('ZVT_DEVICE') or section.get('device'),
        'password': password or env.get('ZVT_PASSWORD') or section.get(
            'password') or DEFAULT_PASSWORD,
        'profile': profile,
    }
