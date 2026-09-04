"""A small pyigtl client for manually inspecting UC1 map messages.

This is not an automated test: it needs a running UC1 sender on the other end
of the connection.

Two modes, because there are two senders. By default it waits for each of the
five device names in turn, which is what SLIA-012's arithmetic stand-in sends.
`--session-seconds` instead records everything that arrives over a window and
reports the distinct device names at the end, which is what SLIA-013's genuine
runner needs: that producer sends exactly one map, so the question is not
"did the five arrive" but "did anything other than UC1_MV_CLASS".
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

SIMULATORS_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATORS_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATORS_ROOT))

import pyigtl  # noqa: E402

from stratum_sim import contract  # noqa: E402

DEFAULT_RECEIVE_TIMEOUT_SEC = 10.0


def describeMessage(mapName: str, message) -> None:
    """Print one message's identity, shape and complete metadata dictionary."""
    print(f"Map role:         {mapName}")
    print(f"Device name:      {message.device_name}")
    print(f"Image shape:      {message.image.shape}  (k, j, i[, components])")
    print(f"Scalar type:      {message.image.dtype}")
    print(f"Header version:   {message.header_version}")
    print("Metadata:")
    for key, value in sorted(message.metadata.items()):
        print(f"  {key} = {value}")
    if not message.metadata:
        print("  (none) - the sender dropped its provenance attributes")
    print()


def recordSession(client, seconds: float) -> int:
    """Record every message that arrives over a window and name every device.

    A producer that sends one map cannot be checked by waiting for five names.
    What matters is the opposite: that nothing else was sent. Mixing a real map
    with stand-in maps in one session would imply UC1 produced all five.
    """
    deadline = time.monotonic() + seconds
    deviceCounts: Counter[str] = Counter()
    described: set[str] = set()

    while time.monotonic() < deadline:
        for message in client.get_latest_messages():
            deviceName = message.device_name
            deviceCounts[deviceName] += 1
            if deviceName not in described:
                described.add(deviceName)
                mapName = message.metadata.get(contract.METADATA_RESULT_MAP_KEY, "(no role)")
                describeMessage(mapName, message)
        time.sleep(0.05)

    if not deviceCounts:
        print(f"ERROR: nothing arrived in {seconds:.1f} s.", file=sys.stderr)
        return 1

    print(f"-- Session summary over {seconds:.1f} s --")
    for deviceName, count in sorted(deviceCounts.items()):
        print(f"  {deviceName}: {count} message(s)")
    uc1Devices = sorted(name for name in deviceCounts if name.startswith("UC1_"))
    print(f"  Distinct UC1_* device names: {', '.join(uc1Devices) or '(none)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect UC1 map messages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=contract.UC1_MAP_PORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_RECEIVE_TIMEOUT_SEC)
    parser.add_argument(
        "--session-seconds",
        dest="sessionSeconds",
        type=float,
        default=0.0,
        help="Record everything that arrives for this many seconds instead of "
        "waiting for the five stand-in device names.",
    )
    arguments = parser.parse_args(argv)

    client = pyigtl.OpenIGTLinkClient(host=arguments.host, port=arguments.port)
    print(f"Connecting to {arguments.host}:{arguments.port} ...")
    try:
        if arguments.sessionSeconds > 0.0:
            return recordSession(client, arguments.sessionSeconds)
        for mapName, deviceName in contract.UC1_MAP_DEVICE_NAMES.items():
            message = client.wait_for_message(deviceName, timeout=arguments.timeout)
            if message is None:
                print(
                    f"ERROR: no {mapName} message ({deviceName}) arrived before the timeout.",
                    file=sys.stderr,
                )
                return 1
            describeMessage(mapName, message)
    finally:
        client.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
