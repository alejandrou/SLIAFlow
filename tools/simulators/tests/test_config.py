"""Configuration and LiveView stream-shape tests.

Manual step 3 observes the achieved frame rate against a running server; what
is checked here is that the configured preset and device name are what actually
reach the wire.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy

from stratum_sim import config, contract, igtl_transport

BMP_ROW_ALIGNMENT_SAMPLES = 4

# Documented simulator interface and integration contracts.
DOCUMENTED_FRAME_PRESETS = {
    "demo": (160, 120),
    "medium": (320, 240),
    "full": (640, 480),
}
DOCUMENTED_LIVE_VIEW_PORT = 18944


class PresetTest(unittest.TestCase):

    def test_demoIsTheDefaultPreset(self):
        self.assertEqual(config.DEFAULT_PRESET_NAME, "demo")

    def test_presetTableMatchesTheDocumentedInterface(self):
        self.assertEqual(config.FRAME_PRESETS, DOCUMENTED_FRAME_PRESETS)

    def test_everyPresetKeepsBmpRowPaddingAtZero(self):
        for presetName, (samples, _lines) in config.FRAME_PRESETS.items():
            with self.subTest(presetName=presetName):
                self.assertEqual(samples % BMP_ROW_ALIGNMENT_SAMPLES, 0)


class ConfigurationTest(unittest.TestCase):

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        # Windows hands out 8.3 short paths for temporary directories, and the
        # loader resolves the root, so the expectation has to resolve it too.
        self.repositoryRoot = Path(self._temporaryDirectory.name).resolve()
        (self.repositoryRoot / "config").mkdir()
        self.addCleanup(self._temporaryDirectory.cleanup)

    def writeLocalConfig(self, simulatorsBlock: dict) -> None:
        localPath = self.repositoryRoot / "config" / "local.json"
        localPath.write_text(json.dumps({"simulators": simulatorsBlock}), encoding="utf-8")

    def test_defaultsApplyWhenNoLocalConfigExists(self):
        loaded = config.loadSimulatorConfig(self.repositoryRoot)

        self.assertEqual(loaded.presetName, config.DEFAULT_PRESET_NAME)
        self.assertEqual(
            (loaded.samples, loaded.lines), DOCUMENTED_FRAME_PRESETS["demo"]
        )
        self.assertEqual(loaded.liveViewPort, DOCUMENTED_LIVE_VIEW_PORT)
        self.assertEqual(loaded.liveViewDeviceName, "LiveView")
        self.assertTrue(loaded.rotate180)
        self.assertIsNone(loaded.case)
        self.assertEqual(loaded.recordedRoot, self.repositoryRoot / "input" / "bin" / "bin")

    def test_localJsonSimulatorsBlockOverridesDefaults(self):
        self.writeLocalConfig({"preset": "medium", "liveViewPort": 19944, "rotate180": False})

        loaded = config.loadSimulatorConfig(self.repositoryRoot)

        self.assertEqual(
            (loaded.samples, loaded.lines), DOCUMENTED_FRAME_PRESETS["medium"]
        )
        self.assertEqual(loaded.liveViewPort, 19944)
        self.assertFalse(loaded.rotate180)

    def test_anUnknownPresetIsRejectedByName(self):
        self.writeLocalConfig({"preset": "enormous"})

        with self.assertRaises(config.ConfigurationError) as rejected:
            config.loadSimulatorConfig(self.repositoryRoot)
        self.assertIn("enormous", str(rejected.exception))

    def test_retiredSettingsAreUnknown(self):
        # SLIA-025 retired the generated scenes, so the settings that shaped them
        # are refused by name rather than silently ignored: a local.json that
        # still asks for a phantom must not start a session that looks like one.
        retired = (
            "bands",
            "frameSource",
            "sceneMode",
            "seed",
            "noiseCounts",
            "textureFeatureCount",
            "frameCount",
            "datasetRoot",
        )
        for setting in retired:
            with self.subTest(setting=setting):
                self.writeLocalConfig({setting: 1})
                with self.assertRaises(config.ConfigurationError) as rejected:
                    config.loadSimulatorConfig(self.repositoryRoot)
                self.assertIn(f"Unknown simulators setting(s): {setting}.", str(rejected.exception))


class RecordedCaseConfigurationTest(unittest.TestCase):
    """A session names one recorded case by folder name."""

    def setUp(self):
        self._temporaryDirectory = tempfile.TemporaryDirectory()
        self.repositoryRoot = Path(self._temporaryDirectory.name).resolve()
        (self.repositoryRoot / "config").mkdir()
        self.addCleanup(self._temporaryDirectory.cleanup)

    def load(self, **overrides) -> config.SimulatorConfig:
        return config.loadSimulatorConfig(self.repositoryRoot, overrides=overrides)

    def loadRecorded(self, **overrides) -> config.SimulatorConfig:
        settings = {"case": "004-02"}
        settings.update(overrides)
        return self.load(**settings)

    def test_aCaseIsAPlainFolderName(self):
        loaded = self.loadRecorded()
        self.assertEqual(loaded.case, "004-02")
        # Where `.ai/policies/medical-data-policy.md` records the cases live.
        self.assertEqual(loaded.recordedRoot, self.repositoryRoot / "input" / "bin" / "bin")

        # A case is a folder name under the recorded root. A path would let a
        # session read from anywhere while the root claims otherwise.
        for badCase in ("", "..", "bin/004-02", "bin\\004-02"):
            with self.subTest(case=badCase):
                with self.assertRaises(config.ConfigurationError):
                    self.loadRecorded(case=badCase)

    def test_captureDelayBoundsMustBeOrdered(self):
        loaded = self.loadRecorded()
        # "a configurable 5-8 s" capture delay, from the WP5 plan's workstream B.
        self.assertEqual((loaded.captureDelayMinSec, loaded.captureDelayMaxSec), (5.0, 8.0))

        instant = self.loadRecorded(captureDelayMinSec=0.0, captureDelayMaxSec=0.0)
        self.assertEqual((instant.captureDelayMinSec, instant.captureDelayMaxSec), (0.0, 0.0))

        for bounds in (
            {"captureDelayMinSec": -1.0},
            {"captureDelayMinSec": 6.0, "captureDelayMaxSec": 5.0},
        ):
            with self.subTest(bounds=bounds):
                with self.assertRaises(config.ConfigurationError) as refused:
                    self.loadRecorded(**bounds)
                # Refused for the delay, not for some other setting.
                self.assertIn("captureDelay", str(refused.exception))


class LiveViewStreamShapeTest(unittest.TestCase):

    def test_configuredPresetAndDeviceNameReachTheWire(self):
        loaded = config.loadSimulatorConfig(Path(tempfile.gettempdir()) / "stratum-sim-absent")
        frameBgr = numpy.zeros((loaded.lines, loaded.samples, 3), dtype=numpy.uint8)

        message = igtl_transport.buildImageMessage(
            igtl_transport.prepareFrameForWire(frameBgr, rotate180=loaded.rotate180),
            deviceName=loaded.liveViewDeviceName,
            metadata=contract.liveViewMetadata("acquisition stand-in, laptop camera"),
        )

        self.assertEqual(message.device_name, "LiveView")
        self.assertEqual(message.image.shape, (1, loaded.lines, loaded.samples, 3))
        self.assertEqual(message.image.dtype, numpy.uint8)
        self.assertEqual(message.header_version, igtl_transport.IGTL_HEADER_VERSION_WITH_METADATA)

    def test_aRenamedStreamKeepsItsMetadataAndHeaderInAgreement(self):
        # `SLIAFlow.DeviceName` states which producer sent the message. If the
        # stream is renamed and the metadata is not, the message contradicts
        # itself, and the metadata is the half a consumer is asked to trust.
        renamed = "LiveView_Bench2"
        metadata = contract.liveViewMetadata("acquisition stand-in", deviceName=renamed)
        message = igtl_transport.buildImageMessage(
            numpy.zeros((1, 4, 4, 3), dtype=numpy.uint8), deviceName=renamed, metadata=metadata
        )

        self.assertEqual(message.metadata[contract.METADATA_DEVICE_NAME_KEY], renamed)
        self.assertEqual(message.metadata[contract.METADATA_DEVICE_NAME_KEY], message.device_name)
