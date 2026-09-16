"""Configuration for the stand-in simulators.

Settings come from the `simulators` block of `config/local.json`, which is
already ignored by Git. `config/local.example.json` documents the block. Every
key is optional except `case`, which the acquisition stand-in needs from here or
from its command line; the defaults below are what the demo runs on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import contract

# Frame presets are (samples, lines). Every `samples` value is a multiple of 4
# so a BMP row written from a frame needs no padding.
FRAME_PRESETS: dict[str, tuple[int, int]] = {
    "demo": (160, 120),
    "medium": (320, 240),
    "full": (640, 480),
}

DEFAULT_PRESET_NAME = "demo"

# The acquisition stand-in reads one case of the public HSI Human Brain Database
# where it lies, streams the laptop camera on LiveView, and publishes the case's
# cube when a capture is triggered. The LiveView frame and the cube are
# unrelated: the camera stands in for the rig, and the cube was recorded by a
# different one.
#
# Where `.ai/policies/medical-data-policy.md` records the approved cases live.
RECORDED_ROOT_RELATIVE_PATH = Path("input") / "bin" / "bin"

# "a configurable 5-8 s" delay, from the WP5 plan's workstream B. Drawn uniformly
# per capture; both bounds at 0 make a capture instant.
DEFAULT_CAPTURE_DELAY_MIN_SEC = 5.0
DEFAULT_CAPTURE_DELAY_MAX_SEC = 8.0

# `OpenIGTLinkServer.cpp` serves LiveView on 18944. The UC1 map stream is on
# 18945; the acquisition stand-in does not listen on it.
DEFAULT_LIVE_VIEW_PORT = 18944
DEFAULT_LIVE_VIEW_DEVICE_NAME = "LiveView"

CONFIG_FILE_RELATIVE_PATH = Path("config") / "local.json"
CONFIG_BLOCK_NAME = "simulators"


class ConfigurationError(ValueError):
    """The `simulators` block asks for something this simulator cannot do."""


@dataclass(frozen=True)
class SimulatorConfig:
    """Resolved simulator settings.

    `samples` and `lines` are derived from `presetName` rather than stored
    separately, so a preset and an explicit size can never disagree.
    """

    repositoryRoot: Path
    presetName: str = DEFAULT_PRESET_NAME
    webcamIndex: int = 0
    liveViewPort: int = DEFAULT_LIVE_VIEW_PORT
    liveViewDeviceName: str = DEFAULT_LIVE_VIEW_DEVICE_NAME
    targetFrameRate: float = 10.0
    rotate180: bool = True
    case: str | None = None
    recordedRoot: Path | None = None
    hsCubePort: int = contract.HS_CUBE_PORT
    controlPort: int = contract.CONTROL_PORT
    captureDelayMinSec: float = DEFAULT_CAPTURE_DELAY_MIN_SEC
    captureDelayMaxSec: float = DEFAULT_CAPTURE_DELAY_MAX_SEC

    def __post_init__(self) -> None:
        if self.presetName not in FRAME_PRESETS:
            raise ConfigurationError(
                f"Unknown frame preset {self.presetName!r}. "
                f"Choose one of: {', '.join(sorted(FRAME_PRESETS))}."
            )
        if self.case is not None and (
            not self.case
            or self.case in (".", "..")
            or "/" in self.case
            or "\\" in self.case
            or Path(self.case).name != self.case
        ):
            raise ConfigurationError(
                f"case must be one folder name under recordedRoot, not {self.case!r}. A path "
                "would let a session read from somewhere recordedRoot does not say."
            )
        if self.captureDelayMinSec < 0.0 or self.captureDelayMaxSec < self.captureDelayMinSec:
            raise ConfigurationError(
                "The capture delay needs 0 <= captureDelayMinSec <= captureDelayMaxSec, not "
                f"{self.captureDelayMinSec} and {self.captureDelayMaxSec}."
            )
        if self.targetFrameRate <= 0.0:
            raise ConfigurationError(
                f"targetFrameRate must be positive, not {self.targetFrameRate}."
            )
        if self.recordedRoot is None:
            object.__setattr__(
                self, "recordedRoot", self.repositoryRoot / RECORDED_ROOT_RELATIVE_PATH
            )

    @property
    def samples(self) -> int:
        return FRAME_PRESETS[self.presetName][0]

    @property
    def lines(self) -> int:
        return FRAME_PRESETS[self.presetName][1]


def repositoryRootFromHere() -> Path:
    """Return the repository root, found by walking up from this file."""
    # tools/simulators/stratum_sim/config.py -> stratum_sim -> simulators -> tools -> root
    return Path(__file__).resolve().parents[3]


def _readSimulatorsBlock(repositoryRoot: Path) -> dict[str, Any]:
    configPath = repositoryRoot / CONFIG_FILE_RELATIVE_PATH
    if not configPath.is_file():
        return {}

    try:
        document = json.loads(configPath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"{configPath} is not valid JSON: {error}") from error

    block = document.get(CONFIG_BLOCK_NAME, {})
    if not isinstance(block, dict):
        raise ConfigurationError(
            f"The {CONFIG_BLOCK_NAME!r} entry in {configPath} must be an object."
        )
    return block


def loadSimulatorConfig(
    repositoryRoot: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> SimulatorConfig:
    """Build the simulator configuration from defaults, local.json, and overrides.

    Overrides come from the command line and win over the file, which wins over
    the defaults. An unrecognised key is an error rather than a silent no-op:
    a mistyped setting that quietly does nothing is worse than one that stops.
    """
    root = (repositoryRoot or repositoryRootFromHere()).resolve()
    settings: dict[str, Any] = dict(_readSimulatorsBlock(root))
    settings.update({key: value for key, value in (overrides or {}).items() if value is not None})

    if "preset" in settings:
        settings["presetName"] = settings.pop("preset")
    if settings.get("recordedRoot") is not None:
        settings["recordedRoot"] = Path(str(settings["recordedRoot"])).expanduser()

    known = {field for field in SimulatorConfig.__dataclass_fields__ if field != "repositoryRoot"}
    unknown = sorted(set(settings) - known)
    if unknown:
        raise ConfigurationError(
            f"Unknown {CONFIG_BLOCK_NAME} setting(s): {', '.join(unknown)}. "
            f"Known settings: {', '.join(sorted(known))}."
        )

    return replace(SimulatorConfig(repositoryRoot=root), **settings)
