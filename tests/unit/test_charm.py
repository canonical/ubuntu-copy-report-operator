# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Unit tests for the charm."""

from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
from charmlibs.apt import PackageError, PackageNotFoundError
from ops.testing import (
    ActiveStatus,
    BlockedStatus,
    Context,
    State,
)

from charm import UbuntuCopyReportCharm


@pytest.fixture
def ctx():
    return Context(UbuntuCopyReportCharm)


@pytest.fixture
def base_state():
    return State(leader=True)


@patch("charm.CopyReport.install")
@patch("charm.CopyReport.setup_systemd_units")
def test_install_event_sets_active_status_on_success(
    setup_units_mock, install_mock, ctx, base_state
):
    state_in = State(leader=True)

    out = ctx.run(ctx.on.install(), state_in)

    assert out.unit_status == ActiveStatus()
    install_mock.assert_called_once()
    setup_units_mock.assert_called_once()


@patch("charm.CopyReport.install")
@pytest.mark.parametrize(
    "exception",
    [
        PackageError,
        PackageNotFoundError,
        CalledProcessError(1, "foo"),
    ],
)
def test_install_event_blocks_charm_on_environment_setup_failure(
    install_mock, exception, ctx, base_state
):
    install_mock.side_effect = exception

    out = ctx.run(ctx.on.install(), base_state)

    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )


@patch("charm.CopyReport.start")
def test_start_event_sets_active_status(start_mock, ctx, base_state):
    out = ctx.run(ctx.on.start(), base_state)

    assert out.unit_status == ActiveStatus()
    start_mock.assert_called_once()


@patch("charm.CopyReport.start")
def test_start_event_blocks_charm_when_service_start_fails(start_mock, ctx, base_state):
    start_mock.side_effect = CalledProcessError(1, "foo")

    out = ctx.run(ctx.on.start(), base_state)

    assert out.unit_status == BlockedStatus(
        "Failed to start services. Check `juju debug-log` for details."
    )


@patch(
    "charm.UbuntuCopyReportCharm._lpuser_lp_oauthkey",
    new_callable=PropertyMock,
)
@patch("charm.CopyReport.configure_lpoauthkey")
@patch("charm.CopyReport.configure_schedule")
def test_config_changed_event_configures_oauth_and_schedule(
    configure_schedule_mock,
    configure_lpoauth_mock,
    lp_oauth_prop_mock,
    ctx,
):
    state_in = State(leader=True)
    lp_oauth_prop_mock.return_value = "fake-token"
    configure_lpoauth_mock.return_value = True

    out = ctx.run(ctx.on.config_changed(), state_in)

    assert out.unit_status == ActiveStatus()
    configure_lpoauth_mock.assert_called_once_with("fake-token")
    configure_schedule_mock.assert_called_once_with()


def test_config_changed_event_blocks_charm_when_lp_secret_not_configured(ctx, base_state):
    out = ctx.run(ctx.on.config_changed(), base_state)

    assert out.unit_status == BlockedStatus("Launchpad oauth token config missing.")


@patch("charm.CopyReport.run_copy_report")
def test_copy_now_action_triggers_copy_report_and_logs_message(
    run_copy_report_mock, ctx, base_state
):
    out = ctx.run(ctx.on.action("copy-now"), base_state)

    assert ctx.action_logs == ["Running copy-report"]
    assert out.unit_status == ActiveStatus()
    run_copy_report_mock.assert_called_once()


@patch("charm.CopyReport.run_copy_report")
def test_copy_now_action_sets_status_message_when_run_fails(run_copy_report_mock, ctx, base_state):
    run_copy_report_mock.side_effect = CalledProcessError(1, "sync")

    out = ctx.run(ctx.on.action("copy-now"), base_state)

    assert out.unit_status == ActiveStatus(
        "Failed to run copy-report. Check `juju debug-log` for details."
    )


def test_lpuser_secret_property_returns_none_when_secret_not_found():
    dummy = SimpleNamespace()
    dummy.config = {"lpuser_secret_id": "missing"}
    dummy.model = MagicMock()
    dummy.model.get_secret.side_effect = ops.SecretNotFoundError

    result = UbuntuCopyReportCharm._lpuser_secret.fget(dummy)

    assert result is None


def test_lpuser_lp_oauthkey_property_returns_none_when_key_missing_from_secret():
    dummy = SimpleNamespace()
    fake_secret = MagicMock()
    fake_secret.get_content.return_value = {}
    dummy._lpuser_secret = fake_secret

    result = UbuntuCopyReportCharm._lpuser_lp_oauthkey.fget(dummy)

    assert result is None
