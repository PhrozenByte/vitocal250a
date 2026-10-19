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

from contextlib import suppress

from PyViCare.PyViCare import PyViCare
from PyViCare.PyViCareBrowserOAuthManager import ViCareBrowserOAuthManager
from PyViCare.PyViCareCachedServiceBase import ViCareCachedServiceBase
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
