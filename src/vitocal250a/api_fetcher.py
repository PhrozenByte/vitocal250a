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

import re
import tomllib
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter
from typing import Any, cast

from PyViCare.PyViCare import PyViCare
from PyViCare.PyViCareBrowserOAuthManager import ViCareBrowserOAuthManager
from PyViCare.PyViCareCachedServiceBase import ViCareCachedServiceBase
from PyViCare.PyViCareHeatingDevice import HeatingCircuit
from PyViCare.PyViCareHeatPump import HeatPump
from PyViCare.PyViCareUtils import PyViCareNotSupportedFeatureError
from requests.adapters import HTTPAdapter
from urllib3 import Retry


def init_vicare(
    client_id: str, token_file: str
) -> tuple[PyViCare, ViCareCachedServiceBase, HeatPump]:
    # initialize PyViCare
    vicare = PyViCare()

    # minimize API requests as much as possible
    vicare.loadViaGateway()

    # set a 30min cache duration
    # we invalidate and refresh the cache manually anyway
    vicare.setCacheDuration(1800)  # type: ignore[no-untyped-call]

    # initialize browser-based OAuth
    # you can also provide a pre-authenticated token_file instead
    # mount a retry adapter so that network issues don't bring the app down immediately
    oauth_manager = ViCareBrowserOAuthManager(client_id, token_file)

    retry = Retry(total=5, connect=3, read=3, backoff_factor=0.2)

    adapter = HTTPAdapter(max_retries=retry)
    oauth_manager.oauth_session.mount("https://", adapter)
    oauth_manager.oauth_session.mount("http://", adapter)

    vicare.initWithExternalOAuth(oauth_manager)

    # get and verify heat pump
    if not vicare.devices:
        raise RuntimeError("No Viessmann device found")

    heatpump = None
    for device in vicare.devices:
        device = device.asAutoDetectDevice()
        if isinstance(device, HeatPump):
            heatpump = device
            break

    if heatpump is None:
        raise RuntimeError("No heating device found")

    model = None
    with suppress(PyViCareNotSupportedFeatureError):
        model = heatpump.getProperty("device.variant")["properties"]["value"]["value"]
    if model != "Vitocal250A":
        raise RuntimeError(
            f"Expecting heating device to be a 'Vitocal250A', got {model!r} instead"
        )

    # get API service
    service = heatpump.service
    assert isinstance(service, ViCareCachedServiceBase)

    return vicare, service, heatpump


@dataclass
class Value:
    key: str
    name: str

    unit: str = field(default="", repr=False, kw_only=True)
    hidden: bool = field(default=False, repr=False, kw_only=True)

    heatpump: HeatPump = field(repr=False, kw_only=True)
    service: ViCareCachedServiceBase = field(init=False, repr=False)

    value: object | None = field(default=None, init=False, repr=False)
    timestamp: datetime | None = field(default=None, init=False, repr=False)
    updated: bool | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        service = cast(ViCareCachedServiceBase, self.heatpump.service)
        if not isinstance(service, ViCareCachedServiceBase):
            raise ValueError(
                f"Invalid ViCare service: Expecting a {ViCareCachedServiceBase!r} "
                f"instance, got {service!r}"
            )
        self.service = service

    def _fetch_data(self) -> tuple[object, datetime]:
        raise NotImplementedError

    def fetch_data(self) -> tuple[object, datetime, bool]:
        value, timestamp = self._fetch_data()
        updated = (
            self.timestamp is None
            or abs(timestamp.timestamp() - self.timestamp.timestamp()) >= 1
        )

        self.value = value
        self.timestamp = timestamp
        self.updated = updated
        return value, timestamp, updated


@dataclass
class FeatureValue(Value):
    feature_name: str = field(init=False, repr=False)
    property_name: str = field(default="value", init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()

        match = re.fullmatch(r"(?P<feature_name>[^[]+)\[(?P<property_name>[^]]+)]$", self.key)
        if match is not None:
            self.feature_name = match["feature_name"]
            self.property_name = match["property_name"]
        else:
            self.feature_name = self.key

    def _fetch_data(self) -> tuple[object, datetime]:
        data = self.heatpump.getProperty(self.feature_name)
        value = data["properties"][self.property_name]["value"]
        timestamp = datetime.fromisoformat(data["timestamp"]).astimezone()
        return value, timestamp


@dataclass
class FetchTimeValue(Value):
    unit: str = field(default="+00:00", repr=False, kw_only=True)

    def _fetch_data(self) -> tuple[object, datetime]:
        timestamp = self.service.cache_time.astimezone()
        value = timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        return value, timestamp


@dataclass
class ApiRequestValue(Value):
    hidden: bool = field(default=True, repr=False, kw_only=True)

    def _fetch_data(self) -> tuple[object, datetime]:
        timestamp = self.service.cache_time.astimezone()
        return True, timestamp


@dataclass
class OnOffStatusValue(FeatureValue):
    property_name: str = field(default="status", init=False, repr=False)

    def _fetch_data(self) -> tuple[object, datetime]:
        value, timestamp = super()._fetch_data()
        return value == "on", timestamp


@dataclass
class TargetTemperatureValue(Value):
    circuit: HeatingCircuit = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()

        match = re.fullmatch(r"heating\.circuits\.([0-9]+)\.target_temperature$", self.key)
        if match is None:
            raise ValueError(
                f"Invalid key: Key name must match "
                f"'heating.circuits.{{circuit_id}}.target_temperature', got {self.key!r}"
            )
        self.circuit = self.heatpump.getCircuit(match[1])  # type: ignore[no-untyped-call]

    def _fetch_data(self) -> tuple[object, datetime]:
        active_program_data = self.circuit.getProperty(
            f"heating.circuits.{self.circuit.id}.operating.programs.active"
        )
        active_program = active_program_data["properties"]["value"]["value"]

        try:
            data = self.circuit.getProperty(
                f"heating.circuits.{self.circuit.id}.operating.programs.{active_program}"
            )
            value = data["properties"]["temperature"]["value"]
            timestamp = data["timestamp"]
        except (PyViCareNotSupportedFeatureError, KeyError):
            match active_program:
                case "standby":
                    value = None
                    timestamp = active_program_data["timestamp"]
                case "holiday":
                    value = self.circuit.getReducedTemperature()
                    timestamp = active_program_data["timestamp"]
                case _:
                    raise

        return value, datetime.fromisoformat(timestamp).astimezone()


class GetterProxy[ObjectType]:
    _obj: ObjectType

    def __init__(self, obj: ObjectType) -> None:
        self._obj = obj

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get") and name.endswith("()"):
            getter_name = name[:-2]
            getter = getattr(self._obj, getter_name)
            if callable(getter):
                return getter()
        return getattr(self._obj, name)


def get_features(features_file_path: Path, heatpump: HeatPump) -> dict[str, Value]:
    tpl_vars: dict[str, list[object]] = {
        "heatpump": [GetterProxy(heatpump)],
        "circuit": [GetterProxy(circuit) for circuit in heatpump.circuits],
        "coolingCircuit": [
            GetterProxy(coolingCircuit) for coolingCircuit in heatpump.coolingCircuits
        ],
        "burner": [GetterProxy(burner) for burner in heatpump.burners],
        "compressor": [GetterProxy(compressor) for compressor in heatpump.compressors],
        "condensor": [GetterProxy(condensor) for condensor in heatpump.condensors],
        "evaporator": [GetterProxy(evaporator) for evaporator in heatpump.evaporators],
        "inverter": [GetterProxy(inverter) for inverter in heatpump.inverters],
        "fan": [GetterProxy(fan) for fan in heatpump.fans],
    }
    tpl_var_regex: str = "|".join([re.escape(field_var) for field_var in tpl_vars])

    features: dict[str, Value] = {}
    with features_file_path.open("rb") as features_file:
        features_raw: dict[str, dict[str, Any]] = tomllib.load(features_file)
        for key, data in features_raw.items():
            tpl_var_name: str | None = None
            for _, tpl_field_name, _, _ in Formatter().parse(key):
                if tpl_field_name is None:
                    continue

                match = re.match(rf"({tpl_var_regex})(?:\.|$)", tpl_field_name)
                if match is None:
                    raise ValueError(
                        f"Invalid field {key!r}: Invalid key: "
                        f"Unknown variable: {tpl_field_name!r}"
                    )
                if tpl_var_name is not None and tpl_var_name != match[1]:
                    raise ValueError(
                        f"Invalid field {key!r}: Invalid key: "
                        f"Conflicting variables: {tpl_var_name!r} and {match[1]!r}"
                    )
                tpl_var_name = match[1]

            name: str = data.pop("name", "")
            if not name:
                raise ValueError(f"Invalid field {key!r}: Missing name")

            factory: type[Value] = VALUE_CLASSES[""]
            if "class" in data:
                if data["class"] not in VALUE_CLASSES:
                    raise ValueError(f"Invalid field {key!r}: Unknown class: {data['class']!r}")
                factory = VALUE_CLASSES[data.pop("class")]

            if tpl_var_name is not None:
                for tpl_var in tpl_vars[tpl_var_name]:
                    feature = factory(
                        key.format(**{tpl_var_name: tpl_var}),
                        name.format(**{tpl_var_name: tpl_var}),
                        **data,
                        heatpump=heatpump,
                    )
                    features[feature.key] = feature
            else:
                feature = factory(key, name, **data, heatpump=heatpump)
                features[feature.key] = feature

    return features


VALUE_CLASSES: dict[str, type[Value]] = {
    "": FeatureValue,
    "feature": FeatureValue,
    "target_temperature": TargetTemperatureValue,
    "on_off_status": OnOffStatusValue,
    "api_request": ApiRequestValue,
    "fetch_time": FetchTimeValue,
}
