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
red banner with the truncated detail on a smaller second line beneath it, and
the panel status is prefixed `SIMULATED: `. The headline is chosen from that
detail. A detail beginning `real UC1 pipeline` gets `SIMULATED INPUT - REAL UC1
PIPELINE, NOT A CLINICAL RESULT`; everything else, including an absent detail,
gets `SIMULATED - NOT A GENUINE UC1 RESULT`. Both bar the result from clinical
reading, and the second is the default precisely because a producer that stops
describing itself must not be handed the softer wording. The distinction exists
because the arithmetic stand-in is genuinely not a UC1 result, while the
vendored pipeline run on an invented scene genuinely is one - and a banner an
audience can see is factually wrong is a banner they stop believing. The banner is a pair of text actors, because one text actor
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

## Wire metadata

The provenance attributes above describe MRML node attributes. This section
defines what goes on the OpenIGTLink wire, which is not the same thing.

A producer sends exactly these four string keys:

| Wire key | Value |
| --- | --- |
| `SLIAFlow.ResultMap` | one exact map key from the result-roles table |
| `SLIAFlow.DeviceName` | the exact producer device for that map |
| `SLIAFlow.DataOrigin` | `external-genuine` or `simulated` |
| `SLIAFlow.SimulationDetail` | free text, display-only, optional |

`findResultSource` matches on role, device **and** origin together. A producer
that sends origin alone is received and then never discovered, which looks
exactly like a transport failure and is not one.

The `LiveView` stream carries no `SLIAFlow.ResultMap`. It is the live pane, not
a result map, and claiming a result role for it would make it discoverable as
one.

### Header version 2 is required

Every message must be sent with OpenIGTLink header version 2. This is measured,
not assumed. On pyigtl 0.3.4 a freshly constructed `ImageMessage` has
`header_version = 1`, and packing the four keys at version 1 emits only a
`logger.warning` - "Metadata will not be packed" - then returns a well-formed
146-byte message whose metadata unpacks to `{}`. The identical message at
version 2 packs to 316 bytes and round-trips all four keys.

A version-1 send therefore drops every provenance attribute silently, behind a
successful-looking send and a warning on the wrong side of the wire.

Note also that `metadata` is not a pyigtl constructor argument.
`ImageMessage.__init__` takes only `image`, `ijk_to_world_matrix`,
`world_coordinate_system`, `timestamp` and `device_name`; both `metadata` and
`header_version` are plain attributes assigned after construction.

### The receiver does not see these names verbatim

SLIAFlow's receiving side renames every incoming key.
`vtkMRMLIGTLConnectorNode.cxx` copies incoming metadata onto the MRML node as

```cpp
std::string tag = "OpenIGTLink." + iter->first;
```

unconditionally, so the wire key `SLIAFlow.DataOrigin` arrives as the MRML
attribute `OpenIGTLink.SLIAFlow.DataOrigin`.

Producers send the bare names anyway. The prefix is the receiver's business,
and changing what goes on the wire to pre-compensate would break the real
applications the stand-ins imitate. Reconciling the two names is SLIA-008's
job, and the attribute names SLIAFlow actually reads are established there
rather than assumed here.

The line above was read at commit
`85e5f764f3ad3d4adbaa568db0104b2b8f5998e8`, which is the commit SLIA-007 pins,
so it describes the build SLIAFlow will actually run against.

### Provenance never travels with the endpoint

SLIAFlow must never infer `simulated` from a port or a hostname. A stand-in and
the real application use the same port; the difference between them is what the
metadata says, and nothing else.

## SLIA-012 arithmetic stand-in

No UC1-to-OpenIGTLink wrapper exists upstream. The project therefore supplies a
CUDA-free arithmetic stand-in under `tools/simulators/stratum_sim/uc1_sim.py` to
prove the producer/consumer seam before SLIA-013 connects the genuine binary.
It listens on `127.0.0.1:18945` and sends these five exact device names:

| Map role | Device name |
| --- | --- |
| `tmdMap` | `UC1_TMD` |
| `majorityVotingMap` | `UC1_MV_CLASS` |
| `majorityVotingProbabilityMap` | `UC1_MV_PROB` |
| `svmProbability` | `UC1_SVM_PROB` |
| `knnProbability` | `UC1_KNN_PROB` |

The stand-in derives a redness-index map and a luminance map from the calibrated
cube, feeds those two maps to four fixed logits, and produces the two
probability maps first. `knnProbability` is the same arithmetic at temperature
`1.6`, not a second algorithm. The elementwise mean of those probability maps
then defines the class map, majority-voting probability map and tumour map. The
rule has hand-chosen constants, was not fitted or validated, and has no
diagnostic meaning.

Before each image send, the producer re-checks finite values, contract ranges,
probability sums, class values, and the relationships among all five maps. The
sender also requires `STRATUM SIMULATED CUBE` in `raw.hdr`; the explicit
`--force-unmarked` switch is reserved for an approved synthetic test folder.
That interlock is a data-safety boundary, not evidence that any result is
clinical. An optional `UC1_SIM_NOTICE` STRING message repeats the simulated
provenance on the wire.

## SLIA-013 genuine UC1 runner

The genuine pipeline is connected by `tools/simulators/stratum_sim/uc1_runner.py`,
which builds nothing of its own: it runs the vendored UC1 binary, compiled
unmodified, and reads back what that binary wrote. It listens on the same
`127.0.0.1:18945` and implements the same `Classifier` seam as the stand-in, so
swapping one for the other is stopping a process and starting another.

### A real-UC1 producer supplies one of the five roles

**The genuine binary produces `majorityVotingMap` and nothing else.** `main.cu`
writes `output/rgb/{red,green,blue}.txt` and `output/<dataset>/imageRGB.bmp`;
`tmdMap`, `majorityVotingProbabilityMap`, `svmProbability` and `knnProbability`
are computed on the device and then discarded, and the write that would have
surfaced them is inside a comment block at `main.cu` lines 164-174.

This is a property of the upstream binary, not of SLIAFlow. SLIAFlow's contract
has five roles; a real-UC1 producer currently fills one of them.

Three options exist for the other four, and the chosen default is the third.

1. Run the real binary for `UC1_MV_CLASS` and the stand-in for the other four.
   Rejected. It would require a loud, non-optional distinction in the
   interface - two different `SimulationDetail` strings on two different
   nodes - or it silently implies UC1 produced all five.
2. Add an output path to UC1 so it writes the other four. Out of scope; it
   needs project-owner approval and a separate task, because it means changing
   vendored source.
3. **Leave the four unavailable in real-UC1 mode and show the waiting state.**
   One box, one story, nothing implied.

An absent map is `None` in `Uc1Maps` and is never substituted with zeros. A
consumer must be able to read "this producer did not produce this map" without
being handed a fabricated one, and the real runner and the arithmetic stand-in
are never run in the same session.

### Wire metadata the real runner stamps

| Key | Value |
| --- | --- |
| `SLIAFlow.ResultMap` | `majorityVotingMap` |
| `SLIAFlow.DeviceName` | `UC1_MV_CLASS` |
| `SLIAFlow.DataOrigin` | `simulated` |
| `SLIAFlow.SimulationDetail` | `real UC1 pipeline, synthetic input`, or `real UC1 pipeline, synthetic tissue phantom` for a phantom dataset |

The origin is `simulated` even though the algorithm is genuine, and that is the
point of `SimulationDetail` carrying the distinction. A genuine algorithm run
over an invented scene is not a genuine clinical result, so the origin describes
the data and the detail describes how it was produced. Header version 2 applies
here for the same reason it applies everywhere else: at version 1 all four keys
are silently dropped.

### Recovering the class map

The binary emits colour, not classes, so the class map is recovered by inverting
the palette. The forward table SLIA-012 writes with and the inverse SLIA-013
reads with are one definition in `bmp.py`, exported both ways, so they cannot
drift apart. An RGB triple that is not in the table is reported with its count
and first offending coordinates and fails the run; it is never resolved to the
nearest known colour, because a nearest-colour fallback would turn an unexpected
pipeline output into a plausible-looking class map.

Outputs are checked for freshness rather than existence. UC1 writes the same
three `output/rgb/*.txt` names for every dataset on every run, so an existence
check cannot distinguish this run's output from a previous run's, and a crashed
run that left last week's files behind would pass one. A file that predates the
run fails it.

`docs/development/uc1_local_build.md` records the build, the measured runtime and
VRAM, and what the scene has to look like before UC1 resolves it to anything.

### The input scene is part of the provenance

Two scenes exist and they are not equally fake, so both streams name which one
produced a message:

| Scene | LiveView detail | Map-stream detail | What UC1 makes of it |
| --- | --- | --- | --- |
| channel | `acquisition stand-in, synthetic scene` | `real UC1 pipeline, synthetic input` | every pixel class 4, background |
| tissue phantom | `acquisition stand-in, synthetic tissue phantom` | `real UC1 pipeline, synthetic tissue phantom` | two classes, coherent regions |

The runner decides by looking for the phantom record in the dataset folder, not
by taking a flag, so the detail cannot disagree with the data that was read.
`DataOrigin` stays `simulated` in both cases: the origin describes the data and
never softens because the algorithm is genuine.

The phantom's spectra are built from a haemoglobin absorption and scattering
model so that they have the *shape* of brain reflectance, because UC1 min-max
normalizes each pixel across its bands before its SVM and shape is all that
classifier ever sees. That is what makes a demonstration possible, and it is
also what makes the labelling delicate: a red area over the phantom's
tumour-like region **is not a detection**, and UC1 in fact fails to separate the
phantom's cortex from its tumour-like region at all.
`docs/development/synthetic_tissue_phantom.md` records the model, the measured
agreement, and what may and may not be claimed.

A consumer must not branch on the detail. It is display-only, it is free text,
and a new scene will add a new string: SLIAFlow reads it to write the second
banner line and for nothing else.

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
