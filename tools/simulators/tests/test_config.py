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


class PresetTest(unittest.TestCase):

    def test_demoIsTheDefaultPreset(self):
        self.assertEqual(config.DEFAULT_PRESET_NAME, "demo")
        self.assertEqual(config.FRAME_PRESETS["demo"], (160, 120))
        self.assertEqual(config.FRAME_PRESETS["medium"], (320, 240))
        self.assertEqual(config.FRAME_PRESETS["full"], (640, 480))

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
        self.assertEqual((loaded.samples, loaded.lines), (160, 120))
        self.assertEqual(loaded.bands, 93)
        self.assertEqual(loaded.frameSource, "synthetic")
        self.assertEqual(loaded.liveViewPort, 18944)
        self.assertEqual(loaded.liveViewDeviceName, "LiveView")
        self.assertTrue(loaded.rotate180)
        self.assertEqual(loaded.noiseCounts, 0)
        self.assertEqual(loaded.datasetRoot, self.repositoryRoot / "workspace" / "simulators" / "datasets")

    def test_localJsonSimulatorsBlockOverridesDefaults(self):
        self.writeLocalConfig({"preset": "medium", "liveViewPort": 19944, "rotate180": False})

        loaded = config.loadSimulatorConfig(self.repositoryRoot)

        self.assertEqual((loaded.samples, loaded.lines), (320, 240))
        self.assertEqual(loaded.liveViewPort, 19944)
        self.assertFalse(loaded.rotate180)

    def test_anUnknownPresetIsRejectedByName(self):
        self.writeLocalConfig({"preset": "enormous"})

        with self.assertRaises(config.ConfigurationError) as rejected:
            config.loadSimulatorConfig(self.repositoryRoot)
        self.assertIn("enormous", str(rejected.exception))

    def test_anUnknownFrameSourceIsRejectedByName(self):
        self.writeLocalConfig({"frameSource": "telepathy"})

        with self.assertRaises(config.ConfigurationError) as rejected:
            config.loadSimulatorConfig(self.repositoryRoot)
        self.assertIn("telepathy", str(rejected.exception))

    def test_settingsThatCouldNotSatisfyTheContractAreRejected(self):
        # A rank cannot exceed the band count, so this cube could never carry
        # the rank the dataset contract requires however it were generated.
        self.writeLocalConfig({"bands": 1})
        with self.assertRaises(config.ConfigurationError) as tooFewBands:
            config.loadSimulatorConfig(self.repositoryRoot)
        self.assertIn(str(config.MINIMUM_BAND_COUNT), str(tooFewBands.exception))

        # The channel basis alone is rank 3, so a cube with no texture features
        # is degenerate: it would be written, load cleanly, and be unusable.
        self.writeLocalConfig({"textureFeatureCount": 0})
        with self.assertRaises(config.ConfigurationError) as tooFewFeatures:
            config.loadSimulatorConfig(self.repositoryRoot)
        self.assertIn(str(config.MINIMUM_TEXTURE_FEATURE_COUNT), str(tooFewFeatures.exception))

        # The lowest settings that can still clear the floor are accepted.
        self.writeLocalConfig(
            {
                "bands": config.MINIMUM_BAND_COUNT,
                "textureFeatureCount": config.MINIMUM_TEXTURE_FEATURE_COUNT,
            }
        )
        loaded = config.loadSimulatorConfig(self.repositoryRoot)
        self.assertEqual(loaded.bands, config.MINIMUM_BAND_COUNT)


class LiveViewStreamShapeTest(unittest.TestCase):

    def test_configuredPresetAndDeviceNameReachTheWire(self):
        loaded = config.loadSimulatorConfig(Path(tempfile.gettempdir()) / "stratum-sim-absent")
        frameBgr = numpy.zeros((loaded.lines, loaded.samples, 3), dtype=numpy.uint8)

        message = igtl_transport.buildImageMessage(
            igtl_transport.prepareFrameForWire(frameBgr, rotate180=loaded.rotate180),
            deviceName=loaded.liveViewDeviceName,
            metadata=contract.liveViewMetadata("acquisition stand-in, synthetic scene"),
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
