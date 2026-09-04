"""Service-path tests for the arithmetic UC1 stand-in."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import numpy

from stratum_sim import contract, uc1_maps, uc1_sim


def validMaps() -> contract.Uc1Maps:
    probabilities = numpy.zeros((1, 2, 3, 4), dtype=numpy.float32)
    probabilities[..., 0] = 1.0
    scalarShape = probabilities.shape[:3]
    return contract.Uc1Maps(
        tmdMap=numpy.zeros(scalarShape, dtype=numpy.float32),
        majorityVotingMap=numpy.ones(scalarShape, dtype=numpy.uint8),
        majorityVotingProbabilityMap=numpy.ones(scalarShape, dtype=numpy.float32),
        svmProbability=probabilities.copy(),
        knnProbability=probabilities.copy(),
    )


class FakeClassifier:

    def __init__(self, maps):
        self.maps = maps
        self.datasets = []

    def classify(self, dataset):
        self.datasets.append(dataset)
        return self.maps


class FakeServer:

    def __init__(self, imageResults=(), noticeResults=(), connectionStates=()):
        self.imageResults = list(imageResults)
        self.noticeResults = list(noticeResults)
        self.connectionStates = list(connectionStates)
        self.images = []
        self.notices = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @property
    def isConnected(self):
        return self.connectionStates.pop(0) if self.connectionStates else True

    def sendImage(self, image, deviceName, metadata):
        self.images.append((image, deviceName, metadata))
        return self.imageResults.pop(0) if self.imageResults else True

    def sendString(self, text, deviceName):
        self.notices.append((text, deviceName))
        return self.noticeResults.pop(0) if self.noticeResults else True


class FakeInterrupt:

    def __init__(self, allowedIterations=100):
        self.allowedIterations = allowedIterations
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @property
    def requested(self):
        self.reads += 1
        return self.reads > self.allowedIterations


class SendMapsTest(unittest.TestCase):

    def test_invalidCollectionIsRejectedBeforeTheFirstSend(self):
        maps = validMaps()
        maps.knnProbability[0, 0, 0, 0] = numpy.nan
        server = FakeServer()

        with self.assertRaises(uc1_maps.MapContractError):
            uc1_sim.sendMaps(server, maps)

        self.assertEqual(server.images, [])

    def test_mutationDuringSendIsCaughtBeforeTheNextMap(self):
        maps = validMaps()

        class MutatingServer(FakeServer):
            def sendImage(self, image, deviceName, metadata):
                result = super().sendImage(image, deviceName, metadata)
                maps.knnProbability[0, 0, 0, 0] = numpy.nan
                return result

        server = MutatingServer()
        with self.assertRaises(uc1_maps.MapContractError):
            uc1_sim.sendMaps(server, maps)
        self.assertEqual(len(server.images), 1)

    def test_successSendsEveryMapInContractOrder(self):
        server = FakeServer()

        self.assertTrue(uc1_sim.sendMaps(server, validMaps()))

        self.assertEqual(
            [deviceName for _image, deviceName, _metadata in server.images],
            [contract.UC1_MAP_DEVICE_NAMES[name] for name in contract.UC1_MAP_FIELD_NAMES],
        )

    def test_failureAtEveryPositionStopsThatCycle(self):
        mapCount = len(contract.UC1_MAP_FIELD_NAMES)
        for failureIndex in range(mapCount):
            with self.subTest(failureIndex=failureIndex):
                server = FakeServer(imageResults=[True] * failureIndex + [False])
                self.assertFalse(uc1_sim.sendMaps(server, validMaps()))
                self.assertEqual(len(server.images), failureIndex + 1)


class StreamMapsTest(unittest.TestCase):

    def dataset(self):
        return contract.DatasetRef(Path("synthetic"), 3, 2, 4, (1.0, 2.0, 3.0, 4.0), True)

    def runStream(self, server, interrupt, *, cycles, sendNotice=False):
        classifier = FakeClassifier(validMaps())
        with (
            mock.patch.object(uc1_sim.igtl_transport, "ImageStreamServer", return_value=server),
            mock.patch.object(uc1_sim.igtl_transport, "InterruptFlag", return_value=interrupt),
            mock.patch.object(uc1_sim.time, "sleep") as sleep,
        ):
            completed = uc1_sim.streamMaps(
                self.dataset(), classifier, cycles=cycles, intervalSec=0.25, sendNotice=sendNotice
            )
        return completed, classifier, sleep

    def test_finiteCycleCountCountsOnlyCompleteFiveMapSends(self):
        # The first cycle fails on map three; only the next two complete cycles count.
        server = FakeServer(imageResults=[True, True, False] + [True] * 10)
        completed, classifier, _sleep = self.runStream(
            server, FakeInterrupt(), cycles=2
        )

        self.assertEqual(completed, 2)
        self.assertEqual(len(classifier.datasets), 1)
        self.assertEqual(len(server.images), 13)

    def test_zeroCyclesStreamsUntilInterrupted(self):
        server = FakeServer()
        completed, _classifier, sleep = self.runStream(
            server, FakeInterrupt(allowedIterations=1), cycles=0
        )

        self.assertEqual(completed, 1)
        sleep.assert_called_once_with(0.25)

    def test_disconnectDoesNotCountACompletedCycle(self):
        server = FakeServer(connectionStates=[False, True])
        completed, _classifier, _sleep = self.runStream(
            server, FakeInterrupt(), cycles=1
        )
        self.assertEqual(completed, 1)
        self.assertEqual(len(server.images), len(contract.UC1_MAP_FIELD_NAMES))

    def test_optionalNoticeRetriesUntilAcceptedThenStops(self):
        server = FakeServer(noticeResults=[False, True])
        completed, _classifier, _sleep = self.runStream(
            server, FakeInterrupt(), cycles=3, sendNotice=True
        )

        self.assertEqual(completed, 3)
        self.assertEqual(
            server.notices,
            [
                (uc1_sim.SIMULATION_NOTICE, uc1_sim.SIMULATION_NOTICE_DEVICE_NAME),
                (uc1_sim.SIMULATION_NOTICE, uc1_sim.SIMULATION_NOTICE_DEVICE_NAME),
            ],
        )


if __name__ == "__main__":
    unittest.main()
