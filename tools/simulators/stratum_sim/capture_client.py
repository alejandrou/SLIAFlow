"""Send one capture trigger to the acquisition stand-in and wait for its answer.

This is the launcher's stand-in for the capture button `SLIA-022` adds to
SLIAFlow. It is short-lived on purpose: it connects, sends one `CAPTURE`,
reports what comes back, and disconnects. A client that stayed attached would be
the second client `SLIA-018` describes the moment Slicer dialled the same port.

Nothing here reads or writes data. It only speaks the control channel's wording,
which `tools/simulators/README.md` states for the Slicer side.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

import pyigtl

from . import contract

EXIT_READY = 0
EXIT_FAILED = 1
EXIT_IGNORED = 2

DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT_SEC = 30.0
POLL_INTERVAL_SEC = 0.02

CAPTURE_NUMBER_PREFIX = "capture="
FOLDER_PREFIX = " folder="


def captureNumber(text: str) -> int | None:
    """Return n from a `... capture=<n> ...` message, or None when it has none.

    Only the part before `folder=` is searched, because the folder is the rest
    of the line and a path may contain anything.
    """
    for field in text.split(FOLDER_PREFIX, 1)[0].split():
        if field.startswith(CAPTURE_NUMBER_PREFIX):
            try:
                return int(field[len(CAPTURE_NUMBER_PREFIX):])
            except ValueError:
                return None
    return None


def sendCaptureTrigger(
    port: int = contract.CONTROL_PORT,
    host: str = DEFAULT_HOST,
    timeoutSec: float = DEFAULT_TIMEOUT_SEC,
    output: Callable[[str], None] = print,
    waitForReady: bool = True,
) -> int:
    """Trigger one capture and return an exit code for how it ended.

    `EXIT_READY` only for the `READY` of the capture this trigger started. The
    stand-in repeats its state every half second, so a `READY` left over from an
    earlier capture is on the wire before this trigger is even read, and the
    capture number is what tells the two apart.

    With `waitForReady` false, `EXIT_READY` means the capture has started, and
    the client leaves at once. That is what lets a second trigger reach the
    stand-in during the capture delay at all: pyigtl serves one client at a
    time, so a client waiting for `READY` would hold the port for the whole
    delay and the second trigger would only be read after it.
    """
    client = pyigtl.OpenIGTLinkClient(host=host, port=port)
    try:
        deadline = time.monotonic() + timeoutSec
        while not client.is_connected():
            if time.monotonic() > deadline:
                output(
                    f"ERROR: nothing accepted a connection on {host}:{port} within "
                    f"{timeoutSec:g} s. Is the acquisition stand-in running in scene mode "
                    "'recorded'?"
                )
                return EXIT_FAILED
            time.sleep(POLL_INTERVAL_SEC)

        client.send_message(
            pyigtl.StringMessage(
                contract.CAPTURE_COMMAND, device_name=contract.CAPTURE_TRIGGER_DEVICE_NAME
            ),
            wait=True,
        )
        output(f"Sent {contract.CAPTURE_COMMAND} to {host}:{port}.")

        startedCapture: int | None = None
        lastStatus: str | None = None
        while time.monotonic() <= deadline:
            messages = [
                message
                for message in client.get_latest_messages()
                if isinstance(message, pyigtl.StringMessage)
            ]
            # The reply is read before the state: both can arrive in one poll,
            # and the state's READY only counts once the reply has said which
            # capture this trigger started.
            messages.sort(key=lambda message: message.device_name != contract.CAPTURE_REPLY_DEVICE_NAME)

            for message in messages:
                text = message.string
                if message.device_name == contract.CAPTURE_REPLY_DEVICE_NAME:
                    output(f"{message.device_name}: {text}")
                    word = text.split(" ", 1)[0]
                    if word == "IGNORED":
                        return EXIT_IGNORED
                    if word == "REFUSED":
                        return EXIT_FAILED
                    if word == "CAPTURING":
                        startedCapture = captureNumber(text)
                        if not waitForReady:
                            return EXIT_READY
                elif message.device_name == contract.CAPTURE_STATUS_DEVICE_NAME:
                    if text != lastStatus:
                        output(f"{message.device_name}: {text}")
                        lastStatus = text
                    completed = captureNumber(text)
                    if (
                        startedCapture is not None
                        and text.startswith("READY ")
                        and completed is not None
                        and completed >= startedCapture
                    ):
                        return EXIT_READY

            time.sleep(POLL_INTERVAL_SEC)

        output(
            f"ERROR: no final answer to the trigger within {timeoutSec:g} s. The capture delay "
            "may be longer than the timeout, or another client may be holding the control port."
        )
        return EXIT_FAILED
    finally:
        client.stop()


def buildArgumentParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stratum_sim capture",
        description=(
            "Send one CAPTURE to the acquisition stand-in's control port, print its "
            "answer, and exit: 0 when the capture is ready (or, with --no-wait, has "
            "started), 2 when it was ignored because a capture was already running, "
            "1 otherwise."
        ),
    )
    parser.add_argument("--port", type=int, default=contract.CONTROL_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--no-wait",
        dest="waitForReady",
        action="store_false",
        help=(
            "Leave as soon as the capture has started instead of waiting for READY, so "
            "that the control port is free for the next trigger during the delay."
        ),
    )
    parser.add_argument(
        "--timeout",
        dest="timeoutSec",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help="Seconds to wait for a connection and for the final answer together.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = buildArgumentParser().parse_args(argv)
    return sendCaptureTrigger(
        port=arguments.port,
        host=arguments.host,
        timeoutSec=arguments.timeoutSec,
        waitForReady=arguments.waitForReady,
    )


if __name__ == "__main__":
    raise SystemExit(main())
