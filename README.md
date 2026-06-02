# Ubuntu Copy Report Operator

**Ubuntu Copy Report Operator** is a [charm](https://juju.is/charms-architecture)
that runs `copy-report --copy-safe` every hour.

## Behavior

- Scheduled runs every hour via `copy-report.timer`.
- Manual trigger action `copy-now`.
- Uses a Launchpad OAuth token from Juju secret config `lpuser_secret_id`.

## Basic usage

```bash
juju deploy ubuntu-copy-report
juju config ubuntu-copy-report lpuser_secret_id=secret:<uuid>
```

Trigger a manual run:

```bash
juju run ubuntu-copy-report/0 copy-now
```

## Service inspection

```bash
systemctl list-timers --all copy-report.timer
systemctl status copy-report.service
journalctl -u copy-report.service
```

## Testing

For information on tests and development workflows, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Ubuntu Copy Report Operator is released under the [GPL-3.0 license](LICENSE).