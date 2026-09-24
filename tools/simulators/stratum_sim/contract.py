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
