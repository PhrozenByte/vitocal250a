#!/bin/bash
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

set -eu -o pipefail
export LC_ALL=C.UTF-8

[ -v CI_TOOLS ] && [ "$CI_TOOLS" == "SGSGermany" ] \
    || { echo "Invalid build environment: Environment variable 'CI_TOOLS' not set or invalid" >&2; exit 1; }
[ -v CI_TOOLS_PATH ] && [ -d "$CI_TOOLS_PATH" ] \
    || { echo "Invalid build environment: Environment variable 'CI_TOOLS_PATH' not set or invalid" >&2; exit 1; }

source "$CI_TOOLS_PATH/helper/common.sh.inc"
source "$CI_TOOLS_PATH/helper/container.sh.inc"
source "$CI_TOOLS_PATH/helper/container-alpine.sh.inc"
source "$CI_TOOLS_PATH/helper/python.sh.inc"

BUILD_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$BUILD_DIR/container.env"

readarray -t -d' ' TAGS < <(printf '%s' "$TAGS")

echo + "CONTAINER=\"\$(buildah from $(quote "$BASE_IMAGE"))\"" >&2
CONTAINER="$(buildah from "$BASE_IMAGE")"

echo + "MOUNT=\"\$(buildah mount $(quote "$CONTAINER"))\"" >&2
MOUNT="$(buildah mount "$CONTAINER")"

echo + "rsync -v -rl --exclude .gitignore ./src/ …/" >&2
rsync -v -rl --exclude '.gitignore' "$BUILD_DIR/src/" "$MOUNT/"

echo + "rsync -v -rl --exclude .gitignore ../pyproject.toml ../src/vitocal250a …/usr/src/vitocal250a/" >&2
rsync -v -rl --exclude '.gitignore' \
    "$BUILD_DIR/../pyproject.toml" "$BUILD_DIR/../src/vitocal250a" \
    "$MOUNT/usr/src/vitocal250a"

user_add "$CONTAINER" vitocal250a 65536 "/var/local/vitocal250a"

cmd buildah run "$CONTAINER" -- \
    chown vitocal250a:vitocal250a "/var/local/vitocal250a"

pkg_install "$CONTAINER" --virtual .run-deps \
    python3

python_pip_install "$CONTAINER"

if [ -n "${PYVICARE_PIP_INSTALL:-}" ]; then
    cmd buildah run "$CONTAINER" -- \
        pip install --user "$PYVICARE_PIP_INSTALL"
fi

cmd buildah run "$CONTAINER" -- \
    pip install --user "/usr/src/vitocal250a"

echo + "rm -rf …/usr/src/vitocal250a" >&2
rm -rf "$MOUNT/usr/src/vitocal250a"

python_pip_cleanup "$CONTAINER"

cleanup "$CONTAINER"

con_cleanup "$CONTAINER"

cmd buildah config \
    --volume "/var/local/vitocal250a" \
    "$CONTAINER"

cmd buildah config \
    --workingdir "/var/local/vitocal250a" \
    --entrypoint '[ "/entrypoint.sh" ]' \
    --cmd '[ "vitocal250a-monitor", "--csv", "monitor.csv", "--monitor", "120" ]' \
    "$CONTAINER"

cmd buildah config \
    --annotation org.opencontainers.image.title="Viessmann Vitocal 250-A" \
    --annotation org.opencontainers.image.description="A container to manage a Viessmann Vitocal 250-A heat pump." \
    --annotation org.opencontainers.image.url="https://github.com/PhrozenByte/vitocal250a" \
    --annotation org.opencontainers.image.authors="Daniel Rudolf" \
    --annotation org.opencontainers.image.vendor="Daniel Rudolf" \
    --annotation org.opencontainers.image.base.name="$BASE_IMAGE" \
    --annotation org.opencontainers.image.base.digest="$(podman image inspect --format '{{.Digest}}' "$BASE_IMAGE")" \
    --annotation org.opencontainers.image.created="$(date -u +'%+4Y-%m-%dT%H:%M:%SZ')" \
    "$CONTAINER"

con_commit "$CONTAINER" "$IMAGE" "${TAGS[@]}"
