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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, cast

from PyViCare.PyViCareCachedServiceBase import ViCareCachedServiceBase
from PyViCare.PyViCareDevice import Device
from PyViCare.PyViCareHeatingDevice import HeatingCircuit
from PyViCare.PyViCareHeatPump import HeatPump
from PyViCare.PyViCareUtils import PyViCareNotSupportedFeatureError


@dataclass
class Value:
    name: str
    unit: str = field(default="", repr=False, kw_only=True)

    value: object | None = field(default=None, init=False, repr=False)
    timestamp: datetime | None = field(default=None, init=False, repr=False)

    last_value: object | None = field(default=None, init=False, repr=False)
    last_timestamp: datetime | None = field(default=None, init=False, repr=False)

    @property
    def key(self) -> str:
        raise NotImplementedError

    def _fetch_data(self) -> tuple[object, datetime]:
        raise NotImplementedError

    def fetch_data(self) -> tuple[object, datetime, bool]:
        value, timestamp = self._fetch_data()
        updated = (
            self.last_timestamp is None
            or abs(timestamp.timestamp() - self.last_timestamp.timestamp()) >= 1
        )

        self.last_value = value
        self.last_timestamp = timestamp
        return value, timestamp, updated


@dataclass
class FeatureValue(Value):
    device: Device
    feature_name: str
    property_name: str = "value"

    @property
    def key(self) -> str:
        if self.property_name != "value":
            return f"{self.feature_name}[{self.property_name}]"
        return self.feature_name

    def _fetch_data(self) -> tuple[object, datetime]:
        data = self.device.getProperty(self.feature_name)
        value = data["properties"][self.property_name]["value"]
        timestamp = datetime.fromisoformat(data["timestamp"]).astimezone()
        return value, timestamp


@dataclass
class FetchTimeValue(Value):
    service: ViCareCachedServiceBase

    @property
    def key(self) -> str:
        return "fetch_time"

    def _fetch_data(self) -> tuple[object, datetime]:
        timestamp = self.service.cache_time.astimezone()
        value = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return value, timestamp


@dataclass
class TargetTemperatureValue(Value):
    circuit: HeatingCircuit

    @property
    def key(self) -> str:
        return f"heating.circuits.{self.circuit.id}.target_temperature"

    @property
    def device(self) -> Device:
        return self.circuit.device

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


def get_features(heatpump: HeatPump) -> Iterator[Value]:
    service = cast(ViCareCachedServiceBase, heatpump.service)
    assert isinstance(service, ViCareCachedServiceBase)

    # basic info
    # static, but potentially interesting values:
    # - heating.configuration.bufferCylinderSize
    # - heating.configuration.centralHeatingCylinderSize
    # - heating.configuration.dhwCylinderSize
    # zero values, but might change in the future:
    # - heating.configuration.houseHeatingLoad
    yield FetchTimeValue("Abfragezeit", service)
    yield FeatureValue("Wifi Signalstärke", heatpump, "tcu.wifi", "strength", unit=" dBm")
    yield FeatureValue(
        "Außentemperatur", heatpump, "heating.sensors.temperature.outside", unit=" °C"
    )

    # circuits
    for circuit in heatpump.circuits:
        # for schedule see heating.circuits.1.heating.schedule
        yield FeatureValue(
            f"{circuit.getName()} Modus",
            heatpump,
            f"heating.circuits.{circuit.id}.operating.modes.active",
        )
        # for "holiday" program schedule see heating.operating.programs.holiday
        # for "holidayAtHome" program schedule see heating.operating.programs.holidayAtHome
        # programs to evaluate (see heating.circuits.1.operating.programs.*):
        # - standby
        # - frostprotection (enables heating.circuits.1.frostprotection?)
        # - fixed (what is that?)
        # - forcedLastFromSchedule
        # - holidayAtHome (should exist, but doesn't?)
        yield FeatureValue(
            f"{circuit.getName()} Programm",
            heatpump,
            f"heating.circuits.{circuit.id}.operating.programs.active",
        )
        # masks target temperatures:
        # - heating.circuits.1.operating.programs.reducedHeating
        # - heating.circuits.1.operating.programs.normalHeating
        # - heating.circuits.1.operating.programs.comfortHeating
        yield TargetTemperatureValue(
            f"{circuit.getName()} Ziel-Raumtemperatur", circuit, unit=" °C"
        )
        yield FeatureValue(
            f"{circuit.getName()} Vorlauftemperatur",
            heatpump,
            f"heating.circuits.{circuit.id}.sensors.temperature.supply",
            unit=" °C",
        )
        # should be equal to heating.boiler.temperature.current
        # heatpump-internal value of `circuit.getTargetSupplyTemperature()`
        # uses heating.circuits.1.heating.curve next to buffer and outside temperatures
        # compressor won't start right away, see heating.configuration.temperature.outside.DampingFactor
        # for min/max values see heating.circuits.1.temperature.levels
        yield FeatureValue(
            f"{circuit.getName()} Ziel-Vorlauftemperatur",
            heatpump,
            f"heating.circuits.{circuit.id}.temperature",
            unit=" °C",
        )
        yield FeatureValue(
            f"{circuit.getName()} Heizkreispumpe Status",
            heatpump,
            f"heating.circuits.{circuit.id}.circulation.pump",
            "status",
        )

    # boiler
    # replaces heating.buffer.sensors.temperature.main
    yield FeatureValue(
        "Pufferspeicher Temperatur",
        heatpump,
        "heating.bufferCylinder.sensors.temperature.main",
        unit=" °C",
    )

    # heating device
    # unknown sensors, require verification:
    # - heating.heatGeneration.0.secondaryCircuit.sensors.temperature
    #   (should replace heating.sensors.temperature.allengra, but doesn't exist, and is zero)
    # - heating.sensors.valve.0.expansion.target
    # - heating.sensors.valve.1.expansion.target
    # - heating.valves.fourThreeWay.position
    yield FeatureValue(
        "Wärmeerzeuger Vorlauftemperatur",
        heatpump,
        "heating.boiler.sensors.temperature.commonSupply",
        unit=" °C",
    )
    yield FeatureValue(
        "Wärmeerzeuger Rücklauftemperatur",
        heatpump,
        "heating.sensors.temperature.return",
        unit=" °C",
    )
    yield FeatureValue(
        "Wärmeerzeuger Anlagendruck", heatpump, "heating.sensors.pressure.supply", unit=" bar"
    )
    yield FeatureValue(
        "Wärmeerzeuger Interne Pumpe Status",
        heatpump,
        "heating.boiler.pumps.internal",
        "status",
    )
    # for target percentage see heating.boiler.pumps.internal.target
    yield FeatureValue(
        "Wärmeerzeuger Interne Pumpe Aktiv",
        heatpump,
        "heating.boiler.pumps.internal.current",
        unit="%",
    )
    # will be replaced by heating.heatGeneration.0.secondaryCircuit.sensors.volumetricFlow
    yield FeatureValue(
        "Wärmeerzeuger Volumenstrom",
        heatpump,
        "heating.sensors.volumetricFlow.allengra",
        unit=" l/h",
    )
    # for valve status see heating.primaryCircuit.valves.fourThreeWay
    yield FeatureValue(
        "Wärmeerzeuger Primärkreis",
        heatpump,
        "heating.primaryCircuit.sensors.temperature.supply",
        unit=" °C",
    )
    # for operation status see heating.secondaryCircuit.operation.state
    # should, in practice, always match heating.circuits.1.operating.modes.active
    # for valve status see heating.secondaryCircuit.valves.fourThreeWay
    yield FeatureValue(
        "Wärmeerzeuger Sekundärkreis",
        heatpump,
        "heating.secondaryCircuit.sensors.temperature.supply",
        unit=" °C",
    )
    yield FeatureValue(
        "Wärmeerzeuger Entfrostung", heatpump, "heating.outdoor.defrosting", "active"
    )

    # fans
    for fan in heatpump.fans:
        yield FeatureValue(
            f"Lüfter {int(fan.component) + 1}",
            heatpump,
            f"heating.primaryCircuit.fans.{fan.component}.current",
            unit="%",
        )

    # compressors
    for compressor in heatpump.compressors:
        # internal sensors, require verification:
        # - heating.compressors.0.heater.crankcase
        # - heating.compressors.0.sensors.pressure.inlet
        # - heating.compressors.0.sensors.temperature.inlet
        # - heating.compressors.0.sensors.temperature.motorChamber
        # - heating.compressors.0.sensors.temperature.oil
        # - heating.compressors.0.sensors.temperature.outlet
        yield FeatureValue(
            "Verdichter Status", heatpump, f"heating.compressors.{compressor.id}", "active"
        )
        yield FeatureValue(
            "Verdichter Phase", heatpump, f"heating.compressors.{compressor.id}", "phase"
        )
        # for target rpm see heating.compressors.0.speed.setpoint
        yield FeatureValue(
            "Verdichter Geschwindigkeit",
            heatpump,
            f"heating.compressors.{compressor.id}.speed.current",
            unit=" rpm",
        )
        yield FeatureValue(
            "Verdichter Betriebsstunden",
            heatpump,
            f"heating.compressors.{compressor.id}.statistics",
            "hours",
            unit=" h",
        )
        yield FeatureValue(
            "Verdichter Starts",
            heatpump,
            f"heating.compressors.{compressor.id}.statistics",
            "starts",
        )

    # condensers
    # internal sensors, require verification:
    # - heating.condensors.0.sensors.temperature.liquid

    # economizers
    # internal sensors, require verification:
    # - heating.economizers.0.sensors.temperature.liquid

    # evaporators
    # internal sensors, require verification:
    # - heating.evaporators.0.heater.base
    # - heating.evaporators.0.sensors.temperature.liquid
    # - heating.evaporators.0.sensors.temperature.overheat

    # heating rods
    # currently there are no heating rods installed, otherwise see:
    # - heatingRods.heatGeneration.N.statistics (replaces heating.heatingRod.statistics)
    # - heatingRods.heatGeneration.N (replaces heating.configuration.heatingRod.*)
    # - heating.heatingRod.heating (replaces heating.heatingRod)

    # inverters
    for inverter in heatpump.inverters:
        # internal sensors, require verification:
        # - heating.inverters.0.sensors.temperature.powerModule
        yield FeatureValue(
            "Inverter Strom",
            heatpump,
            f"heating.inverters.{inverter.id}.sensors.power.current",
            unit=" A",
        )
        yield FeatureValue(
            "Inverter Ausgabeleistung",
            heatpump,
            f"heating.inverters.{inverter.id}.sensors.power.output",
            unit=" W",
        )

    # Domestic Hot Water (DHW)
    # DHW is installed, but currently not being used
    # interesting data points:
    # - heating.dhw.scaldProtection
    # - heating.dhw.temperature.hysteresis

    # energy statistics
    # other, but currently unused statistics:
    # - heating.heat.production.summary.cooling
    # - heating.heat.production.summary.dhw
    # - heating.heatingRod.power.consumption.summary.dhw
    # - heating.heatingRod.power.consumption.summary.heating
    # - heating.power.consumption.dhw
    # - heating.power.consumption.heating
    # - heating.power.consumption.total
    # - heating.power.consumption.summary.cooling
    # - heating.power.consumption.summary.dhw
    # - heating.spf.dhw (replaces heating.scop.dhw)
    # - heating.spf.heating (replaces heating.scop.heating)
    # - heating.spf.total (replaces heating.scop.total)
    yield FeatureValue(
        "Stromverbrauch (Aktuell)", heatpump, "heating.power.consumption.current", unit=" kw"
    )
    yield FeatureValue(
        "Stromverbrauch (Tag)",
        heatpump,
        "heating.power.consumption.summary.heating",
        "currentDay",
        unit=" kw",
    )
    yield FeatureValue(
        "Thermische Leistung (Aktuell)", heatpump, "heating.heat.production.current", unit=" kw"
    )
    yield FeatureValue(
        "Thermische Leistung (Tag)",
        heatpump,
        "heating.heat.production.summary.heating",
        "currentDay",
        unit=" kw",
    )
