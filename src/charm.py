#!/usr/bin/env python3
# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Charmed Operator for Ubuntu Copy Report."""

import logging
import shutil
from subprocess import CalledProcessError, SubprocessError

import ops
from charmlibs.apt import PackageError, PackageNotFoundError

from copy_report import CopyReport

logger = logging.getLogger(__name__)


class UbuntuCopyReportCharm(ops.CharmBase):
    """Charmed Operator for Ubuntu Copy Report."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.copy_now_action, self._on_copy_now)

        self._copy_report = CopyReport()

    @property
    def _lpuser_secret(self) -> ops.model.Secret | None:
        secret_id: str = ""

        try:
            secret_id = str(self.config["lpuser_secret_id"])
        except KeyError:
            logger.warning("lpuser_secret_id config not available, unable to extract keys.")
            return None

        try:
            return self.model.get_secret(id=secret_id)
        except (ops.SecretNotFoundError, ops.model.ModelError):
            logger.warning("Failed to get lpuser secret with id %s", secret_id)

        return None

    @property
    def _lpuser_lp_oauthkey(self) -> str | None:
        secret = self._lpuser_secret

        if secret is not None:
            logger.debug("config - got secret id %s, returning key lpoauthkey", secret)
            try:
                return secret.get_content(refresh=True)["lpoauthkey"]
            except KeyError:
                logger.warning("lpoauthkey not found in lpuser secret.")

        return None

    def _on_install(self, event: ops.EventBase):
        """Handle install and upgrade events."""
        self.unit.status = ops.MaintenanceStatus("Setting up environment")
        try:
            self._copy_report.install()
            self._copy_report.setup_systemd_units()
        except (
            CalledProcessError,
            SubprocessError,
            PackageError,
            PackageNotFoundError,
            ValueError,
            IOError,
            OSError,
            shutil.Error,
        ) as e:
            logger.warning("Failed to set up the environment: %s", e)
            self.unit.status = ops.BlockedStatus(
                "Failed to set up the environment. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_start(self, event: ops.StartEvent):
        """Trigger an initial copy-report run."""
        self.unit.status = ops.MaintenanceStatus("Starting copy-report")
        try:
            self._copy_report.start()
        except CalledProcessError:
            self.unit.status = ops.BlockedStatus(
                "Failed to start services. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event):
        """Update configuration."""
        logger.debug("config changed event")
        self.unit.status = ops.MaintenanceStatus("Updating configuration")

        lp_key_data = self._lpuser_lp_oauthkey
        if lp_key_data is None:
            logger.warning("Launchpad credentials unavailable, unable to run copy-report.")
            self.unit.status = ops.BlockedStatus("Launchpad oauth token config missing.")
            return False
        else:
            logger.debug("config - got lpoauthkey (length %d)", len(lp_key_data))
            if not self._copy_report.configure_lpoauthkey(lp_key_data):
                self.unit.status = ops.BlockedStatus("Failed to update Launchpad oauth token.")
                return False
        logger.debug("config change done - lp oauth key set")

        try:
            self._copy_report.configure_schedule()
        except IOError:
            self.unit.status = ops.BlockedStatus(
                "Failed to write copy-report configuration. Check `juju debug-log` for details."
            )
            return False

        self.unit.status = ops.ActiveStatus()

    def _on_copy_now(self, event: ops.ActionEvent):
        """Trigger an immediate copy-report execution."""
        self.unit.status = ops.MaintenanceStatus("Running copy-report")

        try:
            event.log("Running copy-report")
            self._copy_report.run_copy_report()
        except (CalledProcessError, IOError):
            event.log("copy-report run failed")
            self.unit.status = ops.ActiveStatus(
                "Failed to run copy-report. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuCopyReportCharm)
