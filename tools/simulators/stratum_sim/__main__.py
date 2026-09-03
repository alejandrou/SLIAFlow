"""Command-line entry point for the STRATUM stand-in simulators.

Usage:

    python -m stratum_sim acquisition [options]

More simulators join this dispatch as they are written: the stand-in UC1 map
sender in SLIA-012 and the genuine UC1 runner in SLIA-013.
"""

from __future__ import annotations

import sys

SIMULATOR_NAMES = ("acquisition",)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if not arguments or arguments[0] in ("-h", "--help"):
        print(__doc__.strip())
        print()
        print(f"Simulators: {', '.join(SIMULATOR_NAMES)}")
        return 0 if arguments else 1

    simulatorName, remaining = arguments[0], arguments[1:]
    if simulatorName == "acquisition":
        from .acquisition_sim import main as acquisitionMain

        return acquisitionMain(remaining)

    print(
        f"Unknown simulator {simulatorName!r}. Choose one of: {', '.join(SIMULATOR_NAMES)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
