# Simulated Result Verification

This is the approved developer path for creating a simulated result source by
hand, so the SLIAFlow demo mode and its banner can be verified without the
stand-in producer processes of `SLIA-011` to `SLIA-013`.

It is a Python-console procedure on purpose. It must not become a
user-interface affordance: SLIAFlow never generates result data, and adding a
"simulate" button would make it a producer of the thing it exists to refuse to
invent.

## Boundaries

- The data below is arithmetic, not a classification. It carries no clinical
  meaning of any kind.
- Nothing here may be run against, or alongside, private or identifiable
  patient data.
- Demo mode is transient. It is off on entering the module, off after a scene
  close, and is never written to a saved scene. If a screenshot of a simulated
  result is ever taken, the banner must be visible in it.

## Procedure

Open SLIAFlow in the Slicer executable configured in `config/local.json`, with
Developer Mode enabled, then run the following in the Python console.

```python
import numpy as np, slicer
from SLIAFlowLib import (RESULT_MAP_TMD, RESULT_MAP_DEVICE_NAMES,
                         RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_SOURCE_ORIGIN_ATTRIBUTE,
                         RESULT_SOURCE_DEVICE_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN,
                         RESULT_SOURCE_DETAIL_ATTRIBUTE)
device = RESULT_MAP_DEVICE_NAMES[RESULT_MAP_TMD]
node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", device)
slicer.util.updateVolumeFromArray(node, np.linspace(0, 1, 64*64, dtype=np.float32).reshape(1, 64, 64))
node.SetAttribute(RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_MAP_TMD)
node.SetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN)
node.SetAttribute(RESULT_SOURCE_DEVICE_ATTRIBUTE, device)
node.SetAttribute(RESULT_SOURCE_DETAIL_ATTRIBUTE, "arithmetic stand-in, not a classifier")
```

Then, in the module panel:

| # | Action | Expected observation |
| --- | --- | --- |
| 1 | Leave demo mode unticked and press **Refresh Result** | The right pane stays black; the status reads `WARN: Waiting for genuine UC1_TMD result.` |
| 2 | Tick **Demo mode** | The gradient appears under a red `SIMULATED - NOT A GENUINE UC1 RESULT` banner, with `arithmetic stand-in, not a classifier` on a smaller second line; the status is prefixed `SIMULATED: ` |
| 3 | Press **Refresh Result** again | The banner and its detail line are still there; a slice-view rebuild does not lose them |
| 4 | Set the origin to `external-genuine` (below), untick demo mode, press **Refresh Result** | The map displays with no banner and a normal status, even though the detail attribute is still set |
| 5 | Switch to Welcome and back to SLIAFlow | Demo mode is unticked, the result pane is black, and the waiting status is shown |

For step 4:

```python
from SLIAFlowLib import RESULT_SOURCE_GENUINE_ORIGIN
node.SetAttribute(RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_GENUINE_ORIGIN)
```

## Checking precedence

With both a genuine and a simulated source in the scene for the same map role,
the genuine one must win and no banner may appear, even with demo mode on:

```python
simulated = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "simulated-tmd")
slicer.util.updateVolumeFromArray(simulated, np.full((1, 64, 64), 0.5, dtype=np.float32))
for attribute, value in ((RESULT_SOURCE_ROLE_ATTRIBUTE, RESULT_MAP_TMD),
                         (RESULT_SOURCE_ORIGIN_ATTRIBUTE, RESULT_SOURCE_SIMULATED_ORIGIN),
                         (RESULT_SOURCE_DEVICE_ATTRIBUTE, device)):
    simulated.SetAttribute(attribute, value)
```

## Cleaning up

```python
slicer.mrmlScene.Clear()
```

Untick demo mode before leaving the module. Leaving the scene populated with
marked simulated nodes is the one way this procedure can mislead a later
session.
