"""A small pyigtl client for observing the LiveView stream by hand.

This is manual verification step 3, not an automated test: it needs a running
acquisition simulator on the other end, so it is deliberately not named
`test_*` and is never collected by `run_tests.py`.

    .\\.venv\\Scripts\\python.exe tools\\simulators\\tests\\liveview_client.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SIMULATORS_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATORS_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATORS_ROOT))

import pyigtl  # noqa: E402

from stratum_sim import contract  # noqa: E402

DEFAULT_FRAME_COUNT = 60
RECEIVE_TIMEOUT_SEC = 10.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Receive LiveView frames and report the rate.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18944)
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAME_COUNT)
    arguments = parser.parse_args(argv)

    client = pyigtl.OpenIGTLinkClient(host=arguments.host, port=arguments.port)
    print(f"Connecting to {arguments.host}:{arguments.port} ...")

    receivedCount = 0
    firstArrival: float | None = None

    try:
        while receivedCount < arguments.frames:
            message = client.wait_for_message(
                contract.LIVE_VIEW_DEVICE_NAME, timeout=RECEIVE_TIMEOUT_SEC
            )
            if message is None:
                print("ERROR: no LiveView message arrived before the timeout.", file=sys.stderr)
                return 1

            if firstArrival is None:
                firstArrival = time.perf_counter()
                print(f"Device name:      {message.device_name}")
                print(f"Image shape:      {message.image.shape}  (k, j, i, components)")
                print(f"Scalar type:      {message.image.dtype}")
                print(f"Coordinate sys.:  {message.world_coordinate_system}")
                print(f"Header version:   {message.header_version}")
                print("Metadata:")
                for key, value in sorted(message.metadata.items()):
                    print(f"  {key} = {value}")
                if not message.metadata:
                    print("  (none) - the sender dropped its provenance attributes")
                print()

            receivedCount += 1
    finally:
        client.stop()

    elapsed = time.perf_counter() - (firstArrival or time.perf_counter())
    achievedFrameRate = (receivedCount - 1) / elapsed if elapsed > 0.0 and receivedCount > 1 else 0.0
    print(f"Received {receivedCount} frames in {elapsed:.2f} s -> {achievedFrameRate:.2f} fps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
