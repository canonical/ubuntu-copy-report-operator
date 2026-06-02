# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Representation of a single Ubuntu copy-report worker."""

import logging
import os
import shutil
from pathlib import Path

from charmlibs import apt, pathops, systemd
from charmlibs.apt import PackageError, PackageNotFoundError

logger = logging.getLogger(__name__)

PACKAGES = [
    "python3-apt",
    "python3-launchpadlib",
    "python3-requests",
    "dpkg-dev",
]

COPY_REPORT_SERVICE = "copy-report"
COPY_REPORT_RUNNER_PATH = Path("/usr/bin/run-copy-report")
LP_OAUTH_KEY_PATH = "/home/ubuntu/.config/lp-ubuntu-copy-report-bot.oauth"


class CopyReport:
    """Represent an instance running Ubuntu copy-report."""

    def __init__(self):
        logger.debug("CopyReport class init")
        self.env = os.environ.copy()
        self.proxies = {}
        juju_http_proxy = self.env.get("JUJU_CHARM_HTTP_PROXY")
        juju_https_proxy = self.env.get("JUJU_CHARM_HTTPS_PROXY")
        if juju_http_proxy:
            logger.debug("Setting HTTP_PROXY env to %s", juju_http_proxy)
            self.env["HTTP_PROXY"] = juju_http_proxy
            self.proxies["http"] = juju_http_proxy
        if juju_https_proxy:
            logger.debug("Setting HTTPS_PROXY env to %s", juju_https_proxy)
            self.env["HTTPS_PROXY"] = juju_https_proxy
            self.proxies["https"] = juju_https_proxy

    def _install_packages(self):
        """Install required apt packages."""
        apt.update()
        logger.debug("Apt index refreshed.")

        for package in PACKAGES:
            try:
                apt.add_package(package)
                logger.debug("Package %s installed", package)
            except PackageNotFoundError:
                logger.error("Failed to find package %s in package cache", package)
                raise
            except PackageError as e:
                logger.error("Failed to install %s: %s", package, e)
                raise

    def install(self):
        """Set up environment required for copy-report."""
        self._install_packages()

        shutil.copy("src/script/copy-report", "/usr/bin/copy-report")
        shutil.copy("src/script/run-copy-report", COPY_REPORT_RUNNER_PATH)
        os.chmod("/usr/bin/copy-report", 0o755)
        os.chmod(COPY_REPORT_RUNNER_PATH, 0o755)

    def start(self):
        """Trigger copy-report asynchronously once."""
        systemd.service_start(f"{COPY_REPORT_SERVICE}.service", "--no-block")

    def configure_lpoauthkey(self, lp_key_data: str):
        """Create or refresh the credentials file for launchpad access."""
        lp_key_file = pathops.LocalPath(LP_OAUTH_KEY_PATH)
        parent_dir = lp_key_file.parent
        os.makedirs(parent_dir, exist_ok=True)

        key_success = False
        try:
            lp_key_file.write_text(
                lp_key_data,
                mode=0o600,
                user="ubuntu",
                group="ubuntu",
            )
            key_success = True
        except (FileNotFoundError, NotADirectoryError) as e:
            logger.error(
                "Failed to create lp credentials entry due to directory issues: %s",
                str(e),
            )
        except LookupError as e:
            logger.error(
                "Failed to create lp credentials entry due to issues with root user: %s",
                str(e),
            )
        except PermissionError as e:
            logger.error(
                "Failed to create lp credentials entry due to permission issues: %s",
                str(e),
            )
        logger.debug(
            "configure_lpoauthkey: written lp oauth key (length %d) to %s",
            len(lp_key_data),
            lp_key_file,
        )
        return key_success

    def configure_schedule(self):
        """Write an hourly timer unit."""
        timer_lines = [
            "[Unit]",
            "Description=Ubuntu Copy Report - Scheduled runs",
            "",
            "[Timer]",
            "OnCalendar=hourly",
            "Persistent=true",
            "RandomizedDelaySec=60",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]

        timer_path = Path(f"/etc/systemd/system/{COPY_REPORT_SERVICE}.timer")
        timer_path.write_text("\n".join(timer_lines), encoding="utf-8")
        systemd.daemon_reload()

    def enable_schedule(self):
        """Enable and start the copy-report timer."""
        systemd.service_enable("--now", f"{COPY_REPORT_SERVICE}.timer")

    def disable_schedule(self):
        """Disable and stop the copy-report timer."""
        systemd.service_disable("--now", f"{COPY_REPORT_SERVICE}.timer")

    def run_copy_report(self):
        """Trigger a blocking execution of the copy-report service."""
        systemd.service_start(f"{COPY_REPORT_SERVICE}.service")

    def last_run_failed(self) -> bool:
        """Report whether the copy-report service is currently marked as failed."""
        return systemd.service_failed(f"{COPY_REPORT_SERVICE}.service")

    def setup_systemd_unit(self):
        """Set up copy-report service and timer with proxy configuration."""
        systemd_unit_location = Path("/etc/systemd/system")
        systemd_unit_location.mkdir(parents=True, exist_ok=True)

        service_content = Path(f"src/systemd/{COPY_REPORT_SERVICE}.service").read_text(
            encoding="utf-8"
        )
        timer_content = Path(f"src/systemd/{COPY_REPORT_SERVICE}.timer").read_text(
            encoding="utf-8"
        )

        proxy_env_vars = ""
        if "http" in self.proxies:
            proxy_env_vars += "\nEnvironment=HTTP_PROXY=" + self.proxies["http"]
        if "https" in self.proxies:
            proxy_env_vars += "\nEnvironment=HTTPS_PROXY=" + self.proxies["https"]

        service_content += proxy_env_vars
        (systemd_unit_location / f"{COPY_REPORT_SERVICE}.service").write_text(
            service_content, encoding="utf-8"
        )
        (systemd_unit_location / f"{COPY_REPORT_SERVICE}.timer").write_text(
            timer_content, encoding="utf-8"
        )

    def setup_systemd_units(self):
        """Set up the copy-report service and timer."""
        self.setup_systemd_unit()
