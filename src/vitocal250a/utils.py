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

from datetime import datetime
from fcntl import LOCK_EX, LOCK_SH, LOCK_UN, flock
from pathlib import Path
from types import TracebackType
from typing import Mapping, Self, TextIO, Type, Union


class FileLock:
    _file_handle: TextIO | None = None
    _lock_type: int = LOCK_EX

    _acquired: bool = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def __init__(self, file_handle: TextIO, exclusive: bool = True) -> None:
        self._file_handle = file_handle
        self._lock_type = LOCK_EX if exclusive else LOCK_SH

    def acquire(self) -> None:
        if not self._acquired:
            assert self._file_handle is not None
            flock(self._file_handle, self._lock_type)
            self._acquired = True

    def release(self) -> None:
        if self._acquired:
            assert self._file_handle is not None
            flock(self._file_handle, LOCK_UN)
            self._acquired = False

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()


class LockFile(FileLock):
    _file_path: Path

    def __init__(self, file_path: Path, exclusive: bool = True) -> None:
        self._file_path = file_path
        self._lock_type = LOCK_EX if exclusive else LOCK_SH

    def _open(self) -> None:
        if self._file_handle is None:
            self._file_handle = self._file_path.open("w")

    def _close(self) -> None:
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_path.unlink()

    def acquire(self) -> None:
        self._open()
        super().acquire()

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc_val, exc_tb)
        self._close()


class ValueType[BaseType]:
    value_type: type[BaseType]

    def cast(self, value: object | None) -> BaseType | None:
        if value is None or isinstance(value, self.value_type):
            return value
        if isinstance(value, str):
            return self.from_str(value)
        raise ValueError(f"Failed to cast {value!r} to {self}")

    def from_str(self, value: str) -> BaseType:
        try:
            return self.value_type(value)  # type: ignore[call-arg]
        except Exception as exc:
            raise ValueError(f"Failed to cast {value!r} to {self}") from exc

    def to_str(self, value: BaseType) -> str:
        return str(value)

    def __str__(self) -> str:
        return self.value_type.__name__


class BoolValueType(ValueType[bool]):
    value_type: type[bool] = bool

    def from_str(self, value: str) -> bool:
        if value in {"True", "False", ""}:
            return value == "True"
        raise ValueError(f"Failed to cast {value!r} to {self}")


class IntValueType(ValueType[int]):
    value_type: type[int] = int

    def cast(self, value: object | None) -> int | None:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return super().cast(value)


class FloatValueType(ValueType[float]):
    value_type: type[float] = float

    def cast(self, value: object | None) -> float | None:
        if isinstance(value, int):
            return float(value)
        return super().cast(value)


class StringValueType(ValueType[str]):
    value_type: type[str] = str

    def cast(self, value: object | None) -> str | None:
        return str(value)


class DatetimeValueType(ValueType[datetime]):
    value_type: type[datetime] = datetime

    def from_str(self, value: str) -> datetime:
        return datetime.fromisoformat(value)

    def to_str(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


AnyValueType = Union[
    BoolValueType, IntValueType, FloatValueType, StringValueType, DatetimeValueType
]


VALUE_TYPES: Mapping[str, AnyValueType] = {
    str(value_type): value_type
    for value_type in (
        BoolValueType(),
        IntValueType(),
        FloatValueType(),
        StringValueType(),
        DatetimeValueType(),
    )
}
