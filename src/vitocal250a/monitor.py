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

import csv
import os
import signal
import sys
from argparse import ArgumentParser, Namespace
from contextlib import ExitStack
from csv import DictWriter
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from types import FrameType
from typing import TextIO, cast

from file_read_backwards import FileReadBackwards

from vitocal250a.api_fetcher import get_features, init_vicare
from vitocal250a.utils import FileLock, LockFile, ValueType


def _format_timestamp(timestamp: datetime, reference: datetime) -> str:
    if abs(timestamp.timestamp() - reference.timestamp()) < 1:
        return ""
    if timestamp.date() == reference.date():
        return timestamp.strftime("%H:%M:%S")
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _read_env() -> tuple[str, str]:
    try:
        client_id = os.environ["VICARE_CLIENT_ID"]
    except KeyError:
        print("Missing required environment variable: VICARE_CLIENT_ID", file=sys.stderr)
        raise SystemExit(1)

    try:
        token_file = os.environ["VICARE_TOKEN_FILE"]
    except KeyError:
        token_file = "token.save"

    return client_id, token_file


def _parse_args() -> Namespace:
    parser = ArgumentParser()

    parser.add_argument("--fields", type=str, required=True, help="Fields file name (TOML)")
    parser.add_argument("--status-file", type=str, help="Status file name")
    parser.add_argument("--csv-file", type=str, help="CSV file name")
    parser.add_argument(
        "--monitor", type=int, help="Monitor heat pump and fetch data every n seconds"
    )
    parser.add_argument("--quiet", action="store_true", help="Don't output current status")

    args = parser.parse_args()

    if args.quiet and not args.status_file and not args.csv_file:
        parser.error("--quiet requires passing either --status-file or --csv-file")

    return args


def run_monitor() -> None:
    # read env vars and initialize CLI
    client_id, token_file = _read_env()
    args = _parse_args()

    # initialize PyViCare
    vicare, service, heatpump = init_vicare(client_id, token_file)

    # build features
    features = get_features(Path(args.fields), heatpump)
    feature_keys = list(features.keys())

    with ExitStack() as stack:
        # initialize status file
        status_file: TextIO | None = None
        if args.status_file:
            status_file = stack.enter_context(
                Path(args.status_file).open("w", newline="", encoding="utf-8")
            )

        # initialize CSV file
        csv_file: TextIO | None = None
        csv_file_empty = True
        csv_lock: FileLock | None = None
        csv_writer: DictWriter[str] | None = None

        if args.csv_file:
            csv_file_path = Path(args.csv_file)
            csv_file_empty = not csv_file_path.exists() or csv_file_path.stat().st_size == 0

            # create, acquire and permanently hold exclusive lock on a separate lock file
            # this lock ensures permanent exclusive write access of this monitor
            stack.enter_context(
                LockFile(csv_file_path.with_name(f".{csv_file_path.name}.lock"))
            )

            # open CSV file in append mode
            csv_file = stack.enter_context(
                csv_file_path.open("a", newline="", encoding="utf-8")
            )

            # prepare an exclusive lock on the CSV file
            # don't acquire that lock right away, only when actually writing to the file,
            # or when initially reading from a pre-existing file
            csv_lock = FileLock(csv_file)

            # read existing CSV file
            if not csv_file_empty:
                # verify that the field names of the CSV file match
                with (
                    csv_file_path.open("r", newline="", encoding="utf-8") as csv_reader_io,
                    csv_lock,
                ):
                    csv_reader = csv.DictReader(csv_reader_io, delimiter=";")
                    if csv_reader.fieldnames != feature_keys:
                        raise ValueError(
                            f"Malformed CSV file {args.csv_file!r}: "
                            f"CSV file declares different field names"
                        )

                # read last known feature values from CSV file
                init_features: set[str] = set(features.keys())
                init_features.remove("fetch_time")

                with (
                    FileReadBackwards(csv_file_path, encoding="utf-8") as csv_reader_io,
                    csv_lock,
                ):
                    csv_reader = csv.DictReader(
                        csv_reader_io, fieldnames=feature_keys, delimiter=";"
                    )
                    for row in csv_reader:
                        if (
                            len(init_features) == 0
                            or row["fetch_time"] == "fetch_time"
                            or row["fetch_time"] == features["fetch_time"].name
                            or row["fetch_time"] == features["fetch_time"].unit
                        ):
                            break

                        fetch_time = datetime.fromisoformat(row["fetch_time"])
                        if fetch_time.tzinfo is None:
                            fetch_time = fetch_time.replace(tzinfo=UTC)
                        fetch_time = fetch_time.astimezone()

                        for key, value in row.items():
                            if value and key in init_features:
                                features[key].value = value
                                features[key].timestamp = fetch_time
                                init_features.remove(key)

            # prepare CSV writer
            csv_writer = csv.DictWriter(csv_file, fieldnames=feature_keys, delimiter=";")

        # fetch API and write status
        while True:
            # manually refresh cache
            service.clear_cache()  # type: ignore[no-untyped-call]
            service.fetch_all_features(heatpump.accessor)
            fetch_time = service.cache_time.astimezone()

            # collect data
            data: list[
                tuple[str, str, object, datetime, bool, ValueType[object], str, bool]
            ] = [
                (
                    feature.key,
                    feature.name,
                    *feature.fetch_data(),
                    cast(ValueType[object], feature.value_type),
                    feature.unit,
                    feature.hidden,
                )
                for feature in features.values()
            ]

            # write to CSV file
            # acquire an exclusive lock on the CSV file while writing
            if csv_file is not None:
                assert csv_writer is not None
                assert csv_lock is not None

                with csv_lock:
                    # write header rows
                    if csv_file_empty:
                        csv_writer.writeheader()
                        csv_writer.writerow({key: name for key, name, _, _, _, _, _, _ in data})
                        csv_writer.writerow(
                            {key: str(value_type) for key, _, _, _, _, value_type, _, _ in data}
                        )
                        csv_writer.writerow({key: unit for key, _, _, _, _, _, unit, _ in data})
                        csv_file_empty = False

                    # write data rows
                    rows: dict[datetime, dict[str, object]] = {}
                    for key, _, value, timestamp, updated, value_type, _, _ in data:
                        if updated and key != "fetch_time":
                            timestamp = timestamp.astimezone(UTC).replace(microsecond=0)
                            rows.setdefault(timestamp, {})[key] = value_type.to_str(value)

                    for timestamp, values in sorted(rows.items()):
                        csv_writer.writerow(
                            {"fetch_time": timestamp.strftime("%Y-%m-%d %H:%M:%S"), **values}
                        )

                    # flush CSV file
                    csv_file.flush()

            # write to status file and/or stdout
            if status_file is not None:
                status_file.seek(0)
                status_file.truncate(0)

            if not args.quiet or status_file is not None:
                width_name = max(
                    len(name) for _, name, _, _, _, _, _, hidden in data if not hidden
                )
                width_value = max(
                    len(value_type.to_str(value)) + len(unit)
                    for _, _, value, _, _, value_type, unit, hidden in data
                    if not hidden
                )
                for key, name, value, timestamp, updated, value_type, unit, hidden in data:
                    if hidden:
                        continue
                    if key == "fetch_time":
                        value = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                        unit = timestamp.strftime("%:z")[:6]

                    print_value = f"{value_type.to_str(value)}{unit}"
                    print_timestamp = _format_timestamp(timestamp, fetch_time)
                    status = (
                        f"{name:<{width_name}}  "
                        f"{'' if not args.monitor else '[*]  ' if updated else '     '}"
                        f"{print_value:<{width_value}}  "
                        f"{print_timestamp:<19}"
                    )

                    if not args.quiet:
                        print(status)
                    if status_file is not None:
                        status_file.write(status + "\n")
                        status_file.flush()

            # monitor or finish
            if not args.monitor:
                break

            sleep(args.monitor)

            # clear previous stdout buffer,
            # unless not connected to a tty
            if not args.quiet and sys.stdout.isatty():
                print("\033[F" * len(data), end="")


def monitor() -> None:
    def __handle_signal(signum: int, frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, __handle_signal)
    signal.signal(signal.SIGINT, __handle_signal)

    run_monitor()


if __name__ == "__main__":
    monitor()
