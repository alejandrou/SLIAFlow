"""What `igtl_transport` and its tests share about the wire.

Before SLIA-028 this module held the whole producer/consumer contract of the
standalone acquisition stand-in and UC1 runner: datasets, result maps, capture
control and their metadata. Those processes are gone (ADR-0003, ADR-0004), and
what remains is only what the transport still uses.
"""

from __future__ import annotations

# Wire metadata keys. These are the names that travel on the OpenIGTLink
# connection, and they are sent bare.
#
# SLIAFlow's receiving side does not see them verbatim:
# `vtkMRMLIGTLConnectorNode.cxx` copies incoming metadata onto the MRML node as
#     std::string tag = "OpenIGTLink." + iter->first;
# unconditionally, so the wire key `SLIAFlow.DataOrigin` arrives as the MRML
# attribute `OpenIGTLink.SLIAFlow.DataOrigin`. The prefix is the receiver's
# business. Pre-compensating for it here would break the real applications a
# stand-in imitates.
METADATA_DEVICE_NAME_KEY = "SLIAFlow.DeviceName"
METADATA_DATA_ORIGIN_KEY = "SLIAFlow.DataOrigin"
METADATA_SIMULATION_DETAIL_KEY = "SLIAFlow.SimulationDetail"

DATA_ORIGIN_SIMULATED = "simulated"

LIVE_VIEW_DEVICE_NAME = "LiveView"

# IUMA's AcquisitionSystemApp: its base port and the device name each of its three
# servers sends under, at P, P + 1 and P + 2
# (docs/hardware/acquisition_app_and_hardware.md section 4). "Steroscopic" is
# spelled as the app spells it.
APP_BASE_PORT = 18944
STEREO_DEVICE_NAME = "Steroscopic"
HS_CUBE_DEVICE_NAME = "HsCube"
APP_DEVICE_NAMES = (LIVE_VIEW_DEVICE_NAME, STEREO_DEVICE_NAME, HS_CUBE_DEVICE_NAME)

# Per-band metadata of the SLIA-035 stand-in for that app. The app's binary shows
# no per-band metadata, so these keys are the stand-in's own assumption, named in
# SLIAFlow's namespace so that nobody mistakes them for IUMA's; SLIA-030 checks
# what the real app sends. The band number counts from 1, as the panel shows it.
METADATA_BAND_NUMBER_KEY = "SLIAFlow.BandNumber"
METADATA_WAVELENGTH_KEY = "SLIAFlow.WavelengthNm"

# Reserved for producers that do not exist yet. Nothing in this package binds
# them: a panel that is black because nothing listens has to be black for that
# reason and no other.
RESERVED_PORTS = {18948: "Stereoscopic", 18949: "UC2_STO2"}


def liveViewMetadata(
    simulationDetail: str, deviceName: str = LIVE_VIEW_DEVICE_NAME
) -> dict[str, str]:
    """Provenance for the LiveView stream.

    LiveView carries no `SLIAFlow.ResultMap`: it is the live pane, not a result
    map, and claiming a result role for it would make it discoverable as one.
    The origin travels with the data and never with the endpoint, so a consumer
    must never infer `simulated` from the port or the hostname.

    `deviceName` is a parameter rather than the constant because the sender's
    device name is configurable. `SLIAFlow.DeviceName` states which producer
    sent the message, so a hard-coded value would contradict the device name in
    the message header the moment an operator renamed the stream - and the
    metadata is the half a consumer is asked to trust.
    """
    return {
        METADATA_DEVICE_NAME_KEY: deviceName,
        METADATA_DATA_ORIGIN_KEY: DATA_ORIGIN_SIMULATED,
        METADATA_SIMULATION_DETAIL_KEY: simulationDetail,
    }


def hsCubeBandMetadata(
    simulationDetail: str, bandNumber: int, wavelengthNm: float
) -> dict[str, str]:
    """Provenance of one band on the HsCube stream, with the band it is."""
    metadata = liveViewMetadata(simulationDetail, deviceName=HS_CUBE_DEVICE_NAME)
    metadata[METADATA_BAND_NUMBER_KEY] = str(bandNumber)
    metadata[METADATA_WAVELENGTH_KEY] = f"{wavelengthNm:g}"
    return metadata
