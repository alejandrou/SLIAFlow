"""Command-line entry point for the STRATUM stand-in simulators.

Usage:

    python -m stratum_sim acquisition [options]
    python -m stratum_sim uc1-real [options]
    python -m stratum_sim capture [options]

`acquisition` streams the laptop camera and publishes a recorded case's cube on
each capture (SLIA-023). `uc1-real` runs the genuine UC1 CUDA pipeline on a
recorded case, which produces exactly one of the five contract maps (SLIA-013).

`capture` is not a producer. It sends one capture trigger to the acquisition
stand-in and reports the answer (SLIA-023).
"""

from __future__ import annotations

import sys

SIMULATOR_NAMES = ("acquisition", "uc1-real", "capture")


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
    if simulatorName == "uc1-real":
        from .uc1_runner import main as uc1RealMain

        return uc1RealMain(remaining)
    if simulatorName == "capture":
        from .capture_client import main as captureMain

        return captureMain(remaining)

    print(
        f"Unknown simulator {simulatorName!r}. Choose one of: {', '.join(SIMULATOR_NAMES)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
