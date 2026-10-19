# Viessmann Vitocal 250-A
# A very basic management tool for a Viessmann Vitocal 250-A heat pump.
#
# Copyright (c) 2026  Daniel Rudolf
#
# This work is licensed under the terms of the MIT license.
# For a copy, see LICENSE file or <https://opensource.org/licenses/MIT>.
#
# SPDX-License-Identifier: MIT
# License-Filename: LICENSE

from .monitor import run_monitor


def monitor() -> None:
    try:
        run_monitor()
    except KeyboardInterrupt:
        raise SystemExit(130)
