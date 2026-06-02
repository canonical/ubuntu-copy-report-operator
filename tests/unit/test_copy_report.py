# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Unit tests for `src/copy_report.py`."""

from subprocess import CalledProcessError
from unittest.mock import Mock

import pytest

import copy_report
from copy_report import CopyReport


def test_install_packages_calls_apt_update_before_adding_packages(monkeypatch):
    called = []

    monkeypatch.setattr(copy_report.apt, "update", lambda: called.append("update"))
    monkeypatch.setattr(copy_report.apt, "add_package", lambda pkg: called.append(pkg))
    worker = CopyReport()

    worker._install_packages()

    assert called[0] == "update"
    assert set(called[1:]) == set(copy_report.PACKAGES)


def test_install_copies_scripts(monkeypatch):
    monkeypatch.setattr(CopyReport, "_install_packages", lambda self: None)

    ops = []
    monkeypatch.setattr(
        copy_report.shutil, "copy", lambda src, dst: ops.append(("copy", src, dst))
    )
    monkeypatch.setattr(
        copy_report.os, "chmod", lambda path, mode: ops.append(("chmod", str(path)))
    )

    worker = CopyReport()
    worker.install()

    assert ("copy", "src/script/copy-report", "/usr/bin/copy-report") in ops
    assert ("copy", "src/script/run-copy-report", copy_report.COPY_REPORT_RUNNER_PATH) in ops


def test_start_starts_copy_report_service(monkeypatch):
    calls = []
    monkeypatch.setattr(copy_report.systemd, "service_start", lambda *args: calls.append(args))

    worker = CopyReport()
    worker.start()

    assert ("copy-report.service", "--no-block") in calls


def test_run_copy_report_starts_service(monkeypatch):
    starts = []
    monkeypatch.setattr(copy_report.systemd, "service_start", lambda *args: starts.append(args))

    worker = CopyReport()
    worker.run_copy_report()

    assert ("copy-report.service",) in starts


def test_last_run_failed_uses_systemd_failed_state(monkeypatch):
    monkeypatch.setattr(
        copy_report.systemd,
        "service_failed",
        lambda service: service == "copy-report.service",
    )

    worker = CopyReport()

    assert worker.last_run_failed() is True


def test_setup_systemd_unit_writes_service_and_timer_with_proxy_environment(monkeypatch):
    monkeypatch.setenv("JUJU_CHARM_HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("JUJU_CHARM_HTTPS_PROXY", "https://secure.example:8443")

    worker = CopyReport()

    def fake_read_text(self, encoding=None):
        return "[Service]\nExecStart=/bin/true" if self.suffix == ".service" else "[Timer]"

    written = {}

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(copy_report.Path, "read_text", fake_read_text)
    monkeypatch.setattr(copy_report.Path, "write_text", fake_write_text)
    monkeypatch.setattr(
        copy_report.Path, "mkdir", lambda self, parents=False, exist_ok=False: None
    )
    monkeypatch.setattr(copy_report.systemd, "daemon_reload", lambda *args, **kwargs: None)

    worker.setup_systemd_unit()

    svc_path = "/etc/systemd/system/copy-report.service"
    assert svc_path in written
    assert "Environment=HTTP_PROXY=http://proxy.example:8080" in written[svc_path]
    assert "Environment=HTTPS_PROXY=https://secure.example:8443" in written[svc_path]


def test_configure_schedule_writes_timer_and_reloads_systemd(monkeypatch):
    written = {}
    calls = []

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text

    monkeypatch.setattr(copy_report.Path, "write_text", fake_write_text)
    monkeypatch.setattr(
        copy_report.systemd,
        "daemon_reload",
        lambda *args: calls.append(("reload",) + args),
    )
    worker = CopyReport()
    worker.configure_schedule()

    timer_path = "/etc/systemd/system/copy-report.timer"
    assert timer_path in written
    assert "OnCalendar=hourly" in written[timer_path]
    assert ("reload",) in calls


def test_enable_schedule_enables_and_starts_timer(monkeypatch):
    calls = []
    monkeypatch.setattr(copy_report.systemd, "service_enable", lambda *args: calls.append(args))

    worker = CopyReport()
    worker.enable_schedule()

    assert ("--now", "copy-report.timer") in calls


def test_disable_schedule_disables_and_stops_timer(monkeypatch):
    calls = []
    monkeypatch.setattr(copy_report.systemd, "service_disable", lambda *args: calls.append(args))

    worker = CopyReport()
    worker.disable_schedule()

    assert ("--now", "copy-report.timer") in calls


def test_setup_systemd_units_only_sets_up_unit(monkeypatch):
    called = []
    monkeypatch.setattr(CopyReport, "setup_systemd_unit", lambda self: called.append("setup"))
    monkeypatch.setattr(CopyReport, "configure_schedule", lambda self: called.append("schedule"))

    worker = CopyReport()
    worker.setup_systemd_units()

    assert called == ["setup"]


def test_enable_schedule_raises_when_enable_fails(monkeypatch):
    monkeypatch.setattr(copy_report.Path, "read_text", lambda self, encoding=None: "[Service]")
    monkeypatch.setattr(copy_report.Path, "write_text", lambda self, t, encoding=None: None)
    monkeypatch.setattr(copy_report.Path, "mkdir", lambda self, parents=True, exist_ok=True: None)

    def bad_enable(*args, **kwargs):
        raise CalledProcessError(3, "systemctl")

    monkeypatch.setattr(copy_report.systemd, "service_enable", bad_enable)
    worker = CopyReport()

    with pytest.raises(CalledProcessError):
        worker.enable_schedule()


def test_install_packages_raises_when_package_not_found(monkeypatch):
    monkeypatch.setattr(copy_report.apt, "update", lambda: None)

    def bad_add(_):
        raise copy_report.PackageNotFoundError("missing")

    monkeypatch.setattr(copy_report.apt, "add_package", bad_add)
    worker = CopyReport()

    with pytest.raises(copy_report.PackageNotFoundError):
        worker._install_packages()


def test_install_packages_raises_when_package_installation_fails(monkeypatch):
    monkeypatch.setattr(copy_report.apt, "update", lambda: None)

    def bad_add(_):
        raise copy_report.PackageError("install failed")

    monkeypatch.setattr(copy_report.apt, "add_package", bad_add)
    worker = CopyReport()

    with pytest.raises(copy_report.PackageError):
        worker._install_packages()


def test_start_raises_when_systemd_start_fails(monkeypatch):
    monkeypatch.setattr(
        copy_report.systemd,
        "service_start",
        Mock(side_effect=CalledProcessError(1, "systemctl")),
    )

    worker = CopyReport()

    with pytest.raises(CalledProcessError):
        worker.start()
