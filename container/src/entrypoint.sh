#!/bin/sh
# Viessmann Vitocal 250-A
# A container to manage a Viessmann Vitocal 250-A heat pump.
#
# Copyright (c) 2026  Daniel Rudolf
#
# This work is licensed under the terms of the MIT license.
# For a copy, see LICENSE file or <https://opensource.org/licenses/MIT>.
#
# SPDX-License-Identifier: MIT
# License-Filename: LICENSE

set -e

[ $# -gt 0 ] || set -- vitocal250a-monitor
if [ "$1" == "vitocal250a-monitor" ]; then
    # run vitocal250a-monitor unprivileged and with respawn.py
    # respawn after 1, ~4, ~13, ~49, ~179, ~654, and then every 900 seconds,
    # totalling 15 min by the 5th, 60 min by the 8th, and 6 hours by the 28th retry
    # reset the counter after 5 min
    exec su -p -s /bin/sh vitocal250a -c '"$@"' -- '/bin/sh' \
        respawn --sec 1.0 --backoff 3.6571 --max-sec 900 --max-count 28 --reset-counter 300 -- \
        "$@"
fi

exec "$@"
