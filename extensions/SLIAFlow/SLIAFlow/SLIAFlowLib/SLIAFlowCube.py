"""Parse ENVI headers.

`SLIAFlowCalibratedCube` reads the cube's header with it; the cube itself is
read there, and handed to UC1 by `SLIAFlowUc1Input` (SLIA-033).
"""


def parseEnviHeader(text: str) -> dict[str, str]:
    """Return an ENVI header's key/value entries, lower-case keys.

    The brace-delimited wavelength block is consumed and not returned: a
    header may close it on its last value line and put `lines` and `samples`
    after it, so it must be skipped exactly, not line by line.
    """
    values: dict[str, str] = {}
    insideBlock = False
    for rawLine in text.splitlines():
        line = rawLine.split(";", 1)[0].strip()
        if not line:
            continue
        if insideBlock:
            insideBlock = "}" not in line
            continue
        separatorIndex = line.find("=")
        if separatorIndex < 0:
            continue
        key = line[:separatorIndex].strip().lower()
        value = line[separatorIndex + 1:].strip()
        if value.startswith("{"):
            insideBlock = "}" not in value
            continue
        values[key] = value
    return values
