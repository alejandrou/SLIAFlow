"""Command-line entry point for the STRATUM stand-in simulators.

Usage:

    python -m stratum_sim acquisition [options]
    python -m stratum_sim uc1 [options]
    python -m stratum_sim uc1-real [options]

`uc1` is the CUDA-free arithmetic stand-in from SLIA-012, which produces all
five contract maps and is not a classifier. `uc1-real` runs the genuine UC1 CUDA
pipeline from SLIA-013, which produces exactly one of them. They plug into the
same producer/consumer seam, and they are never run together: five maps from two
different boxes in one session would imply UC1 produced all five.
"""

from __future__ import annotations

import sys

SIMULATOR_NAMES = ("acquisition", "uc1", "uc1-real")


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
    if simulatorName == "uc1":
        from .uc1_sim import main as uc1Main

        return uc1Main(remaining)
    if simulatorName == "uc1-real":
        from .uc1_runner import main as uc1RealMain

        return uc1RealMain(remaining)

    print(
        f"Unknown simulator {simulatorName!r}. Choose one of: {', '.join(SIMULATOR_NAMES)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
