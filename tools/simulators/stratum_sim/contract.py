"""The producer/consumer seam the stand-ins and the real components share.

The seam is a **dataset**, not an in-memory cube. SLIA-013's producer is an
executable that is handed a folder path and opens `raw.dat`,
`whiteReference.dat`, `darkReference.dat` and `raw.hdr` itself, so a protocol
that accepted only an array could not express the real producer at all. A
stand-in calls `loadCalibratedCube()`; the real runner uses `dataset.folder` and
never materialises the cube.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy

# Wire metadata keys. These are the names that travel on the OpenIGTLink
# connection, and they are sent bare.
#
# SLIAFlow's receiving side does not see them verbatim:
# `vtkMRMLIGTLConnectorNode.cxx` copies incoming metadata onto the MRML node as
#     std::string tag = "OpenIGTLink." + iter->first;
# unconditionally, so the wire key `SLIAFlow.DataOrigin` arrives as the MRML
# attribute `OpenIGTLink.SLIAFlow.DataOrigin`. The prefix is the receiver's
# business. Pre-compensating for it here would break the real applications this
# stand-in imitates, so reconciling the two names is SLIA-008's job.
METADATA_RESULT_MAP_KEY = "SLIAFlow.ResultMap"
METADATA_DEVICE_NAME_KEY = "SLIAFlow.DeviceName"
METADATA_DATA_ORIGIN_KEY = "SLIAFlow.DataOrigin"
METADATA_SIMULATION_DETAIL_KEY = "SLIAFlow.SimulationDetail"

DATA_ORIGIN_SIMULATED = "simulated"
DATA_ORIGIN_EXTERNAL_GENUINE = "external-genuine"

LIVE_VIEW_DEVICE_NAME = "LiveView"
UC1_MAP_PORT = 18945

# SLIAFlow's `findResultSource` matches on role, device and origin together, so
# a producer that sends origin alone is received and then never discovered.
# That looks exactly like a transport failure and is not one.
UC1_MAP_DEVICE_NAMES = {
    "tmdMap": "UC1_TMD",
    "majorityVotingMap": "UC1_MV_CLASS",
    "majorityVotingProbabilityMap": "UC1_MV_PROB",
    "svmProbability": "UC1_SVM_PROB",
    "knnProbability": "UC1_KNN_PROB",
}

UC1_MAP_FIELD_NAMES = tuple(UC1_MAP_DEVICE_NAMES)


@dataclass(frozen=True)
class DatasetRef:
    """A written ENVI/BSQ dataset, addressed the way both producers address it.

    `wavelengthsNm` is a tuple rather than an array so that two references to
    the same folder compare equal.
    """

    folder: Path
    samples: int
    lines: int
    bands: int
    wavelengthsNm: tuple[float, ...]
    simulated: bool

    def loadCalibratedCube(self) -> numpy.ndarray:
        """Read the dataset and apply UC1's calibration, returning float32 counts.

        The result is a (bands, lines, samples) array of `100 * reflectance`,
        which is the same quantity UC1 computes on the GPU.
        """
        # Imported here rather than at module scope: `envi` builds DatasetRef
        # instances, so a module-level import in this direction would be a cycle.
        from . import envi

        return envi.loadCalibratedCube(self)


@dataclass(frozen=True, eq=False)
class Uc1Maps:
    """The five contract maps, every one of them optional.

    `None` means "this producer did not produce this map". A consumer must never
    substitute zeros for an absent map. SLIA-013's genuine UC1 binary populates
    one field of five, and that has to be representable without lying.
    """

    tmdMap: numpy.ndarray | None = None
    majorityVotingMap: numpy.ndarray | None = None
    majorityVotingProbabilityMap: numpy.ndarray | None = None
    svmProbability: numpy.ndarray | None = None
    knnProbability: numpy.ndarray | None = None

    def presentMapNames(self) -> tuple[str, ...]:
        """Return the names of the maps this producer actually produced."""
        return tuple(
            field.name for field in fields(self) if getattr(self, field.name) is not None
        )


@runtime_checkable
class Classifier(Protocol):
    """Turn a written dataset into whichever UC1 maps the producer can produce.

    Unimplemented here. This is the seam SLIA-012's arithmetic stand-in and
    SLIA-013's genuine CUDA runner plug into.
    """

    def classify(self, dataset: DatasetRef) -> Uc1Maps:
        ...


def loadDataset(folder: Path) -> DatasetRef:
    """Build a DatasetRef from an existing dataset folder.

    The writer returns an equal reference for the dataset it just wrote, so both
    producers reach a dataset by the same route.
    """
    # Imported here rather than at module scope, for the same cycle reason as
    # DatasetRef.loadCalibratedCube.
    from . import envi

    return envi.loadDataset(folder)


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


def resultMapMetadata(mapName: str, dataOrigin: str, simulationDetail: str = "") -> dict[str, str]:
    """Provenance for one UC1 result map, for the producers SLIA-012 and -013 add."""
    if mapName not in UC1_MAP_DEVICE_NAMES:
        raise ValueError(
            f"Unknown result map {mapName!r}. Known maps: {', '.join(UC1_MAP_FIELD_NAMES)}."
        )
    if dataOrigin not in (DATA_ORIGIN_SIMULATED, DATA_ORIGIN_EXTERNAL_GENUINE):
        raise ValueError(
            f"Unknown data origin {dataOrigin!r}. "
            f"Use {DATA_ORIGIN_SIMULATED!r} or {DATA_ORIGIN_EXTERNAL_GENUINE!r}."
        )

    metadata = {
        METADATA_RESULT_MAP_KEY: mapName,
        METADATA_DEVICE_NAME_KEY: UC1_MAP_DEVICE_NAMES[mapName],
        METADATA_DATA_ORIGIN_KEY: dataOrigin,
    }
    if simulationDetail:
        metadata[METADATA_SIMULATION_DETAIL_KEY] = simulationDetail
    return metadata
