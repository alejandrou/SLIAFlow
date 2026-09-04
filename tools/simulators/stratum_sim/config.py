"""Configuration for the stand-in simulators.

Settings come from the `simulators` block of `config/local.json`, which is
already ignored by Git. `config/local.example.json` documents the block. Every
key is optional; the defaults below are what the demo runs on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import spectra

# Frame presets are (samples, lines). Every `samples` value is a multiple of 4
# so a BMP row written from a frame needs no padding.
FRAME_PRESETS: dict[str, tuple[int, int]] = {
    "demo": (160, 120),
    "medium": (320, 240),
    "full": (640, 480),
}

DEFAULT_PRESET_NAME = "demo"

# The Headwall sensor the UC1 pipeline was built around. 93 bands is confirmed
# twice over: it is the band count the shipped `w_vector.bin` is sized for
# (bands * 6 binary classifiers * 4 bytes = 2232 bytes).
DEFAULT_BAND_COUNT = 93

FRAME_SOURCE_NAMES = ("synthetic", "webcam")

# How the spectral scene is built.
#
# `tissue` is the default because it is the only one the genuine UC1 pipeline
# resolves to anything: the `channel` scene is spectrally rich but its spectra
# are mixtures of camera colour curves, and UC1's SVM - which sees only the
# min-max normalized *shape* of each spectrum - classified every pixel of it as
# background. `tissue` builds the shape from haemoglobin absorption and a
# scattering power law instead. See `tissue.py` for what that does and does not
# claim.
#
# `channel` is kept because it is the only mode that can carry a moving scene
# or a webcam: it turns a frame into a cube, where `tissue` renders its frame
# from the cube.
SCENE_MODE_TISSUE = "tissue"
SCENE_MODE_CHANNEL = "channel"
SCENE_MODE_NAMES = (SCENE_MODE_TISSUE, SCENE_MODE_CHANNEL)

# `OpenIGTLinkServer.cpp` serves LiveView on 18944. The UC1 map stream gets
# 18945 in SLIA-012; nothing here listens on it.
DEFAULT_LIVE_VIEW_PORT = 18944
DEFAULT_LIVE_VIEW_DEVICE_NAME = "LiveView"

# The dataset contract requires a band covariance of at least
# `MINIMUM_SPECTRAL_RANK`, and a rank can never exceed the band count, so a cube
# with fewer bands than that cannot satisfy it however it is generated.
MINIMUM_BAND_COUNT = spectra.MINIMUM_SPECTRAL_RANK

# The channel basis reaches `CHANNEL_BASIS_RANK` on its own and each texture
# feature adds one direction, so this many features are needed to clear the
# floor. Below it the writer would produce a rank-deficient cube - a dataset
# that looks valid, loads, and is degenerate.
MINIMUM_TEXTURE_FEATURE_COUNT = spectra.MINIMUM_SPECTRAL_RANK - spectra.CHANNEL_BASIS_RANK

CONFIG_FILE_RELATIVE_PATH = Path("config") / "local.json"
CONFIG_BLOCK_NAME = "simulators"
DATASET_ROOT_RELATIVE_PATH = Path("workspace") / "simulators" / "datasets"


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
    bands: int = DEFAULT_BAND_COUNT
    frameSource: str = "synthetic"
    sceneMode: str = SCENE_MODE_TISSUE
    webcamIndex: int = 0
    liveViewPort: int = DEFAULT_LIVE_VIEW_PORT
    liveViewDeviceName: str = DEFAULT_LIVE_VIEW_DEVICE_NAME
    targetFrameRate: float = 10.0
    rotate180: bool = True
    seed: int = 20260902
    noiseCounts: int = 0
    textureFeatureCount: int = 6
    frameCount: int = 0
    datasetRoot: Path | None = None

    def __post_init__(self) -> None:
        if self.presetName not in FRAME_PRESETS:
            raise ConfigurationError(
                f"Unknown frame preset {self.presetName!r}. "
                f"Choose one of: {', '.join(sorted(FRAME_PRESETS))}."
            )
        if self.frameSource not in FRAME_SOURCE_NAMES:
            raise ConfigurationError(
                f"Unknown frame source {self.frameSource!r}. "
                f"Choose one of: {', '.join(FRAME_SOURCE_NAMES)}."
            )
        if self.sceneMode not in SCENE_MODE_NAMES:
            raise ConfigurationError(
                f"Unknown scene mode {self.sceneMode!r}. "
                f"Choose one of: {', '.join(SCENE_MODE_NAMES)}."
            )
        if self.sceneMode == SCENE_MODE_TISSUE and self.frameSource != "synthetic":
            # In tissue mode the frame is rendered from the cube, so there is
            # nowhere for a camera frame to enter. Accepting the setting and
            # ignoring it would leave an operator believing the phantom was
            # built from what the camera saw.
            raise ConfigurationError(
                f"Scene mode {SCENE_MODE_TISSUE!r} renders its own frame from the phantom cube, "
                f"so it cannot take frames from frameSource {self.frameSource!r}. Use "
                f"sceneMode {SCENE_MODE_CHANNEL!r} to drive the cube from a camera."
            )
        if self.bands < MINIMUM_BAND_COUNT:
            raise ConfigurationError(
                f"bands must be at least {MINIMUM_BAND_COUNT}, not {self.bands}: the dataset "
                f"contract requires a band covariance of rank {spectra.MINIMUM_SPECTRAL_RANK}, "
                "and a rank cannot exceed the band count."
            )
        if self.textureFeatureCount < MINIMUM_TEXTURE_FEATURE_COUNT:
            raise ConfigurationError(
                f"textureFeatureCount must be at least {MINIMUM_TEXTURE_FEATURE_COUNT}, not "
                f"{self.textureFeatureCount}: the channel basis reaches rank "
                f"{spectra.CHANNEL_BASIS_RANK} alone and each feature adds one direction, so "
                f"fewer than {MINIMUM_TEXTURE_FEATURE_COUNT} cannot reach the required rank "
                f"{spectra.MINIMUM_SPECTRAL_RANK}."
            )
        if self.targetFrameRate <= 0.0:
            raise ConfigurationError(
                f"targetFrameRate must be positive, not {self.targetFrameRate}."
            )
        if self.noiseCounts < 0:
            raise ConfigurationError(f"noiseCounts must not be negative, not {self.noiseCounts}.")
        if self.datasetRoot is None:
            object.__setattr__(
                self, "datasetRoot", self.repositoryRoot / DATASET_ROOT_RELATIVE_PATH
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
    if "datasetRoot" in settings and settings["datasetRoot"] is not None:
        settings["datasetRoot"] = Path(str(settings["datasetRoot"])).expanduser()

    known = {field for field in SimulatorConfig.__dataclass_fields__ if field != "repositoryRoot"}
    unknown = sorted(set(settings) - known)
    if unknown:
        raise ConfigurationError(
            f"Unknown {CONFIG_BLOCK_NAME} setting(s): {', '.join(unknown)}. "
            f"Known settings: {', '.join(sorted(known))}."
        )

    return replace(SimulatorConfig(repositoryRoot=root), **settings)
