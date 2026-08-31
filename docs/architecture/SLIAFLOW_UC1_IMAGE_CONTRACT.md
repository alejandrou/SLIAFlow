# SLIAFlow UC1 image contract

This document defines the non-clinical producer/consumer boundary used by the
SLIAFlow result pane. SLIAFlow consumes image data already present in the MRML
scene; it does not calculate, normalize, infer, or clinically interpret UC1
outputs.

## Result roles

The parameter node stores these language-independent result-map keys. The
corresponding producer device name is exact.

| Map key | Producer device | MRML node | Components | Values | Presentation |
| --- | --- | --- | ---: | --- | --- |
| `tmdMap` | `UC1_TMD` | scalar volume | 1 | `float32`, finite, `[0,1]` | continuous probability |
| `majorityVotingMap` | `UC1_MV_CLASS` | scalar volume | 1 | `uint8`, one of `1,2,3,4` | discrete classes |
| `majorityVotingProbabilityMap` | `UC1_MV_PROB` | scalar volume | 1 | `float32`, finite, `[0,1]` | continuous probability |
| `svmProbability` | `UC1_SVM_PROB` | vector volume | 4 | `float32`, finite, `[0,1]` per component | selected component, continuous |
| `knnProbability` | `UC1_KNN_PROB` | vector volume | 4 | `float32`, finite, `[0,1]` per component | selected component, continuous |

The NumPy view returned by `slicer.util.arrayFromVolume` is KJI order: a
scalar volume has shape `(k, j, i)` and a four-component vector volume has
shape `(k, j, i, 4)`. The producer remains responsible for the physical
coordinate system and for preserving the volume orientation metadata.

Class values mean `1 = normal`, `2 = tumour`, `3 = hypervascularized`, and
`4 = background`. SVM and KNN class selection is one-based (`1` through `4`)
and copies only the selected component into the scalar display volume.

## Provenance attributes

An external volume is eligible for normal UI discovery only when all of the
following are true:

```text
SLIAFlow.ResultMap   = <one exact map key above>
SLIAFlow.DataOrigin  = external-genuine
SLIAFlow.DeviceName  = <the exact producer device for that map>
```

For compatibility with a producer that has not yet added the optional device
attribute, the implementation accepts the exact device name as the MRML node
name when `SLIAFlow.DeviceName` is absent. A wrong or present-but-mismatched
device attribute is rejected. A generic volume picker is intentionally not
part of the module UI, so unmarked test, simulated, or ordinary scene volumes
are not selectable through the normal result workflow.

The attributes are a provenance contract between the future external sender
and this prototype; they are not cryptographic authentication.

## Validation and ownership

Before any result is assigned to the result slice view, SLIAFlow checks the
node type, positive image dimensions, component count, VTK/NumPy scalar type,
finite values, probability range, and class values. Validation has no MRML
side effects. Invalid or missing data clears the result view and reports a
waiting/invalid status.

The external source node is never modified or deleted. SLIAFlow owns a
transient scalar display volume for scalar maps and selected SVM/KNN channels,
plus its display node and its probability and class colour nodes. These
module-owned resources are marked `SaveWithScene = false`. While a result is
displayed the parameter node holds exactly two MRML references: the external
source volume and the module-owned display volume.

The display node pins window/level to the contract range - `[0,1]` for
probability maps and `0` to `4` for the class map - and disables automatic
window/level. Presentation therefore always reflects the contract range
instead of stretching a genuine map to its own extrema.

This contract is for prototype visualization and developer verification only.
It does not establish clinical validity, diagnostic meaning, or a safe use of
private or identifiable medical data.
