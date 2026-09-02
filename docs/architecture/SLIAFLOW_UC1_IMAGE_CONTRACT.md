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
part of the module UI, so unmarked test or ordinary scene volumes are not
selectable through the normal result workflow.

The attributes are a provenance contract between the future external sender
and this prototype; they are not cryptographic authentication.

### Simulated origin

`SLIAFlow.DataOrigin = simulated` marks data produced by a process standing
where a real component will stand, rather than by the real component. It is
never discovered or displayed unless the operator has ticked the module's demo
mode, which is transient widget state, defaults to off, is reset on entering
the module and on scene close, and is never written to the parameter node or a
saved scene.

Real-algorithm-on-synthetic-input is still `simulated`. A genuine PCA, SVM or
KNN run over an invented brain is not a genuine clinical result, so the origin
gate stays binary: `external-genuine` or nothing.

Only two origin values are recognized. Absent, empty or unrecognized
provenance is invalid, not a default, and reaches the result view under
neither setting.

### Precedence

Discovery searches for a genuine source for the requested map role first, and
only then, and only in demo mode, for a simulated one. A genuine source
therefore always wins for the same role, so a simulated node left in the scene
cannot displace a real result merely by being created later.

Discovery considers only nodes produced outside SLIAFlow. The module's own
presentation volume carries the role, device and origin attributes copied from
whatever it last displayed, so it is excluded by its `SLIAFlow.Owner`
attribute; without that exclusion the module would rediscover its own output
and re-present stale data as an external result after the real source had left
the scene.

### Simulation detail

```text
SLIAFlow.SimulationDetail = <free text, display-only>
```

The detail is optional and describes *how* a simulated result was produced -
for example, `real UC1 pipeline, synthetic input` against `arithmetic stand-in,
not a classifier`. Both are fake; they are not equally fake, and the second
banner line is what lets a viewer tell them apart.

It is read only once the origin is already `simulated`, is collapsed to a
single line and truncated before it reaches a text actor, and never appears in
any condition that decides whether something is displayable. A node carrying
the detail attribute with a genuine origin is discovered normally and shows no
banner; a node carrying it with no origin at all is never discovered.

### On-screen marking

Whenever a displayed result's origin is simulated, the result view carries a
red banner reading `SIMULATED - NOT A GENUINE UC1 RESULT` with the truncated
detail on a smaller second line beneath it, and the panel status is prefixed
`SIMULATED: `. The banner is a pair of text actors, because one text actor
carries a single text property for its whole string and so cannot render a
second line at a smaller size. The pair is added, removed and re-asserted as a
unit, and is re-asserted on every successful refresh, because the slice view
rebuilds its actors and a lost banner would present simulated data as genuine.

The banner is asserted before the result volume reaches the view, and the view
is flushed once afterwards, so no frame is ever painted with the banner state
and the volume state disagreeing: neither a simulated map before its banner,
nor a genuine map still under one. If the result view is on screen and the
banner cannot be attached to it, the result is withheld and the panel status
says so. A banner that cannot be drawn is a reason not to display, not a
cosmetic loss.

The presented module-owned volume is stamped with the origin it came from and
is named `SLIAFlow UC1 Result (SIMULATED)` while it holds simulated data. It is
renamed on every presentation, not only when simulated, so a node that once
carried simulated data cannot keep the marker while displaying a genuine
result.

## Validation and ownership

Before any result is assigned to the result slice view, SLIAFlow checks the
node type, positive image dimensions, component count, VTK/NumPy scalar type,
finite values, probability range, and class values. Validation has no MRML
side effects. Invalid or missing data clears the result view and reports a
waiting/invalid status.

Provenance and validation are orthogonal. Simulated data passes through the
identical checks and produces the identical messages, so a malformed simulated
map is rejected exactly as a malformed genuine one is.

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
