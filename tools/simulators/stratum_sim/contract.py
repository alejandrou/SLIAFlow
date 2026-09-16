"""The producer/consumer seam the stand-ins and the real components share.

The seam is a **dataset**, not an in-memory cube. SLIA-013's producer is an
executable that is handed a folder path and opens `raw.dat`,
`whiteReference.dat`, `darkReference.dat` and `raw.hdr` itself, so a protocol
that accepted only an array could not express the real producer at all. A
runner uses `dataset.folder` and never materialises the cube.
"""

from __future__ import annotations

import uuid
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
# Carried by every UC1 map, and by `UC1_RGB` when it is sent (ADR-0002). One
# opaque value per classification of one cube: SLIAFlow composites the two only
# when they carry the same one, so a background retained from another run cannot
# match. It is required on maps sent without a background too, because the
# connector never removes an attribute a later message omits: a map without one
# would keep the previous run's ID on its reused node.
METADATA_CAPTURE_ID_KEY = "SLIAFlow.CaptureId"
# Carried by `HSCube` only. The band browser needs each band's wavelength, and
# the folder is where Mode A's algorithms read the same capture from disk.
METADATA_WAVELENGTHS_KEY = "SLIAFlow.WavelengthsNm"
METADATA_DATASET_FOLDER_KEY = "SLIAFlow.DatasetFolder"

DATA_ORIGIN_SIMULATED = "simulated"
DATA_ORIGIN_EXTERNAL_GENUINE = "external-genuine"

LIVE_VIEW_DEVICE_NAME = "LiveView"
UC1_MAP_PORT = 18945

# The WP5 demonstrator's channels, from `docs/architecture/WP5_MS5_DEMO_PLAN.md`.
HS_CUBE_PORT = 18947
HS_CUBE_DEVICE_NAME = "HSCube"
CONTROL_PORT = 18950

# Reserved for producers that do not exist yet. Nothing in this package binds
# them: a panel that is black because nothing listens has to be black for that
# reason and no other.
RESERVED_PORTS = {18948: "Stereoscopic", 18949: "UC2_STO2"}

# The control channel carries three device names, not one. A Slicer connector
# re-sends an outgoing node when a message of the same name updates it, so the
# trigger and everything sent back travel under different names. And pyigtl keeps
# only the latest message per device name on the receiving side, so the one reply
# to a trigger cannot share a name with the state repeated every half second, or
# the state would overwrite it before a client read it.
CAPTURE_TRIGGER_DEVICE_NAME = "CaptureTrigger"
CAPTURE_REPLY_DEVICE_NAME = "CaptureReply"
CAPTURE_STATUS_DEVICE_NAME = "CaptureStatus"
CAPTURE_COMMAND = "CAPTURE"

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

# Three bands of the cube UC1 classified, sent beside `UC1_MV_CLASS` on the same
# connection (SLIA-024, ADR-0001). One producer, one cube, one connection is what
# makes "same capture" a property of the transport rather than an assumption.
UC1_RGB_DEVICE_NAME = "UC1_RGB"


@dataclass(frozen=True)
class DatasetRef:
    """An ENVI/BSQ dataset folder, addressed the way the producers address it.

    `wavelengthsNm` is a tuple rather than an array so that two references to
    the same folder compare equal.

    The one kind of folder that is approved input is a case of the public HSI
    Human Brain Database, identified by the marker in its `gtMap.hdr`, which is
    read and never written. `recorded` says whether this folder is one. A cube
    travels as `simulated` on the wire, because in this repository the
    acquisition is always simulated; that is not a claim about the cube.
    """

    folder: Path
    samples: int
    lines: int
    bands: int
    wavelengthsNm: tuple[float, ...]
    recorded: bool


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

    Unimplemented here. This is the seam SLIA-013's genuine CUDA runner plugs
    into.
    """

    def classify(self, dataset: DatasetRef) -> Uc1Maps:
        ...


def loadDataset(folder: Path) -> DatasetRef:
    """Build a DatasetRef from an existing dataset folder, reading headers only."""
    # Imported here rather than at module scope: `envi` builds DatasetRef
    # instances, so a module-level import in this direction would be a cycle.
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


def recordedCaseDetail(producer: str, caseName: str) -> str:
    """Name a recorded case, and say that only its acquisition was simulated.

    Every producer describes a recorded cube through this one form. A detail
    that did not name the case would leave a viewer to guess what is on screen.
    """
    return f"{producer}, recorded HSI case {caseName} (simulated acquisition)"


def hsCubeMetadata(
    dataset: DatasetRef, simulationDetail: str, deviceName: str = HS_CUBE_DEVICE_NAME
) -> dict[str, str]:
    """Provenance for a published cube.

    Like LiveView it carries no `SLIAFlow.ResultMap`: a cube is an input to the
    algorithms, not a result, and a result role would make it discoverable as
    one.
    """
    return {
        METADATA_DEVICE_NAME_KEY: deviceName,
        METADATA_DATA_ORIGIN_KEY: DATA_ORIGIN_SIMULATED,
        METADATA_SIMULATION_DETAIL_KEY: simulationDetail,
        METADATA_WAVELENGTHS_KEY: ",".join(f"{value:g}" for value in dataset.wavelengthsNm),
        METADATA_DATASET_FOLDER_KEY: str(dataset.folder),
    }


def _assertKnownOrigin(dataOrigin: str) -> None:
    if dataOrigin not in (DATA_ORIGIN_SIMULATED, DATA_ORIGIN_EXTERNAL_GENUINE):
        raise ValueError(
            f"Unknown data origin {dataOrigin!r}. "
            f"Use {DATA_ORIGIN_SIMULATED!r} or {DATA_ORIGIN_EXTERNAL_GENUINE!r}."
        )


def newCaptureId() -> str:
    """One opaque ID for one classification of one cube (ADR-0002).

    Never reuse one for another cube or another classification. Resending a
    result already computed reuses its ID.
    """
    return uuid.uuid4().hex


def _assertCaptureId(captureId: str) -> None:
    if not isinstance(captureId, str) or not captureId.strip():
        raise ValueError(
            f"A UC1 capture ID must be a non-empty string, not {captureId!r}. "
            "Make one per classification with newCaptureId()."
        )


def uc1RgbMetadata(
    dataOrigin: str, simulationDetail: str = "", *, captureId: str
) -> dict[str, str]:
    """Provenance for the cube-derived colour image sent beside a UC1 map.

    It carries no `SLIAFlow.ResultMap`: it is a background for a result, not a
    result, and a result role would make it discoverable as one. Its origin,
    detail and capture ID are the map's, because SLIAFlow composites the two
    only when they agree.
    """
    _assertKnownOrigin(dataOrigin)
    _assertCaptureId(captureId)
    metadata = {
        METADATA_DEVICE_NAME_KEY: UC1_RGB_DEVICE_NAME,
        METADATA_DATA_ORIGIN_KEY: dataOrigin,
    }
    if simulationDetail:
        metadata[METADATA_SIMULATION_DETAIL_KEY] = simulationDetail
    metadata[METADATA_CAPTURE_ID_KEY] = captureId
    return metadata


def resultMapMetadata(
    mapName: str, dataOrigin: str, simulationDetail: str = "", *, captureId: str
) -> dict[str, str]:
    """Provenance for one UC1 result map."""
    if mapName not in UC1_MAP_DEVICE_NAMES:
        raise ValueError(
            f"Unknown result map {mapName!r}. Known maps: {', '.join(UC1_MAP_FIELD_NAMES)}."
        )
    _assertKnownOrigin(dataOrigin)
    _assertCaptureId(captureId)

    metadata = {
        METADATA_RESULT_MAP_KEY: mapName,
        METADATA_DEVICE_NAME_KEY: UC1_MAP_DEVICE_NAMES[mapName],
        METADATA_DATA_ORIGIN_KEY: dataOrigin,
    }
    if simulationDetail:
        metadata[METADATA_SIMULATION_DETAIL_KEY] = simulationDetail
    metadata[METADATA_CAPTURE_ID_KEY] = captureId
    return metadata
