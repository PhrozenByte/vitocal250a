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

import io
from pathlib import Path
from types import TracebackType
from typing import Iterator, Optional, Type, Self


class FileReadBackwards:
    def __init__(
        self,
        path: str | Path,
        encoding: str = "utf-8",
        chunk_size: int = io.DEFAULT_BUFFER_SIZE
    ) -> None: ...

    def __iter__(self) -> Iterator[str]: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> Optional[bool]: ...

    def __next__(self) -> str: ...

    def readline(self) -> str: ...
