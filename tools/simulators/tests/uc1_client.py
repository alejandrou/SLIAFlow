"""A small pyigtl client for manually inspecting all five UC1 map messages.

This is not an automated test: it needs a running UC1 stand-in on the other
end of the connection.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SIMULATORS_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATORS_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATORS_ROOT))

import pyigtl  # noqa: E402

from stratum_sim import contract  # noqa: E402

DEFAULT_RECEIVE_TIMEOUT_SEC = 10.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the five UC1 map messages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=contract.UC1_MAP_PORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_RECEIVE_TIMEOUT_SEC)
    arguments = parser.parse_args(argv)

    client = pyigtl.OpenIGTLinkClient(host=arguments.host, port=arguments.port)
    print(f"Connecting to {arguments.host}:{arguments.port} ...")
    try:
        for mapName, deviceName in contract.UC1_MAP_DEVICE_NAMES.items():
            message = client.wait_for_message(deviceName, timeout=arguments.timeout)
            if message is None:
                print(
                    f"ERROR: no {mapName} message ({deviceName}) arrived before the timeout.",
                    file=sys.stderr,
                )
                return 1
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
    finally:
        client.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
