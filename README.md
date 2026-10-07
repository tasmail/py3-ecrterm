[![Buy me a coffee](https://bmc-cdn.nyc3.digitaloceanspaces.com/BMC-button-images/custom_images/orange_img.png)](https://buymeacoff.ee/tasmail)

ecrterm
=======

Python ZVT 700 interface (electronic cash registers)


Command line interface
----------------------

`zvt` drives a payment terminal from the shell. Install it with the `cli`
extra (Python 3.8+):

```sh
pip install -e ".[cli]"
```

Without a command `zvt` starts an interactive session with slash commands,
tab completion and history. Ctrl+C aborts a running payment while the PT asks
for the card, Ctrl+D leaves the session:

```text
$ zvt --device socket://192.168.1.10:20007
zvt [192.168.1.10:20007] > /status
zvt [192.168.1.10:20007] > /pay 12,50
zvt [192.168.1.10:20007] > /eod
zvt [192.168.1.10:20007] > /help
```

Every command also runs once from scripts. `--json` prints one JSON
object. The exit code is 0 on success, 1 when the PT declined or aborted, 2
on usage errors and 3 on connection errors:

```sh
zvt -d socket://192.168.1.10:20007 pay 1.50
zvt -d COM3 --json diag emv
zvt decode "06 0F 00"          # offline, needs no terminal
zvt -d simulator:// pay 1.99   # built-in terminal simulator, amounts ending in 99 are declined
```

`--log-packets` shows every packet sent and received. To avoid typing the
device, set `ZVT_DEVICE`/`ZVT_PASSWORD` or put profiles into
`~/.config/zvt/config.ini` (`%APPDATA%\zvt\config.ini` on Windows):

```ini
[default]
profile = shop1

[shop1]
device = socket://192.168.1.10:20007
password = 123456
```
