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
from typing import Mapping, Union


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
        if value in ["True", "False", ""]:
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
    "bool": BoolValueType(),
    "int": IntValueType(),
    "float": FloatValueType(),
    "str": StringValueType(),
    "datetime": DatetimeValueType(),
}
