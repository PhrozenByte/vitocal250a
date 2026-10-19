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
    # run vitocal250a-monitor unprivileged
    exec su -p -s /bin/sh vitocal250a -c '"$@"' -- '/bin/sh' "$@"
fi

exec "$@"
