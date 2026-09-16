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

SLIAFlow draws the class map in the UC1 pipeline's own palette, so a map on
screen reads the same as the pipeline's output:

| Class | Meaning | UC1 RGB | SLIAFlow RGBA |
| --- | --- | --- | --- |
| 0 | not a UC1 class | - | `(0, 0, 0, 0)`, fully transparent |
| 1 | normal | `(0, 255, 0)` | `(0.0, 1.0, 0.0, 1.0)` |
| 2 | tumour | `(255, 0, 0)` | `(1.0, 0.0, 0.0, 1.0)` |
| 3 | hypervascularized | `(0, 0, 255)` | `(0.0, 0.0, 1.0, 1.0)` |
| 4 | background | `(0, 0, 0)` | `(0.0, 0.0, 0.0, 1.0)` |

The palette was read from the source the genuine binary is built from, not from
a screenshot. `majorityVoting` in `gpu_single_bsq/source/functions_cuda.cu`
fills a per-pixel buffer in **B, G, R** order, and `writeMatrixRGB` in
`gpu_single_bsq/source/BitmapWriter.cpp` writes it out as R, G, B. Reading the
first function alone swaps tumour and hypervascularized. `CLASS_PALETTE` in
`tools/simulators/stratum_sim/bmp.py` holds the same four colours.
`SLIAFlowTest.test_classColorTableMatchesUc1Palette` asserts every table entry,
and `SLIAFlowTest.test_classMapSlicePipelineEmitsUc1Colors` asserts the RGBA the
display node hands to the slice views for each class, after window/level. Both
compare against a literal copied from the UC1 source, so a change to SLIAFlow's
table is a failing test. A change on the UC1 side is not detected: nothing in
this repository builds from that source, which lives in the ignored
`workspace/`. When the pipeline source changes, read both functions again; the
SHA-256 of the files the palette was read from is recorded in `SLIA-015`.

Class 4 is black, and so is the result view behind it, so a background region is
not visually distinct from an empty view. The result status, not the colour,
tells the operator whether a map is displayed.

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

A real algorithm run on a simulated acquisition is still `simulated`. A genuine
PCA, SVM or KNN run over a recorded cube whose acquisition was simulated is not a
genuine clinical result, so the origin gate stays binary: `external-genuine` or
nothing.

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
for example, `real UC1 pipeline, recorded HSI case 004-02 (simulated
acquisition)`, which names both the producer and the input. The second banner
line is what lets a viewer read that.

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
because the vendored pipeline's output genuinely is a UC1 result, while a
producer that does not say so cannot be vouched for - and a banner an audience
can see is factually wrong is a banner they stop believing. The banner is a pair of text actors, because one text actor
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

A producer sends exactly these five string keys:

| Wire key | Value |
| --- | --- |
| `SLIAFlow.ResultMap` | one exact map key from the result-roles table |
| `SLIAFlow.DeviceName` | the exact producer device for that map |
| `SLIAFlow.DataOrigin` | `external-genuine` or `simulated` |
| `SLIAFlow.SimulationDetail` | free text, display-only, optional |
| `SLIAFlow.CaptureId` | opaque, non-empty, one per classification; required on every map |

`SLIAFlow.CaptureId` is required whether or not a `UC1_RGB` is sent, under
`ADR-0002`; see the `SLIA-024` section below.

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
applications the stand-ins imitate.

The line above was read at commit
`85e5f764f3ad3d4adbaa568db0104b2b8f5998e8`, which is the commit SLIA-007 pins,
so it describes the build SLIAFlow will actually run against.

#### What the pinned build actually produced

The source above says what the receiver should do; the table below is what it
did. It was recorded by connecting a bare `vtkMRMLIGTLConnectorNode` to the
SLIA-012 arithmetic stand-in (retired in `SLIA-025`) on `127.0.0.1:18945` under
`build\SLIAFlow\SlicerWithSLIAFlow.exe` and printing `GetAttributeNames()`
and every value of each received node. All five map nodes carried exactly
these names:

```text
OpenIGTLink.SLIAFlow.DataOrigin        = simulated
OpenIGTLink.SLIAFlow.DeviceName        = UC1_TMD
OpenIGTLink.SLIAFlow.ResultMap         = tmdMap
OpenIGTLink.SLIAFlow.SimulationDetail  = arithmetic stand-in, not a classifier
OriginalNodeName                       = UC1_TMD
```

Three things are worth keeping from that output. The prefixed spelling is the
only spelling that appears - the bare `SLIAFlow.DataOrigin` is absent from
every received node, so a receiver written against it would find nothing and
would look like a transport failure. `OriginalNodeName` is written by
OpenIGTLinkIF itself rather than by the sender, so it is not part of this
contract and nothing reads it. And the node classes and image types the
converter produced match the result-roles table exactly:

| Device | MRML class | Components | Scalar type |
| --- | --- | ---: | --- |
| `UC1_TMD` | `vtkMRMLScalarVolumeNode` | 1 | `float` |
| `UC1_MV_CLASS` | `vtkMRMLScalarVolumeNode` | 1 | `unsigned char` |
| `UC1_MV_PROB` | `vtkMRMLScalarVolumeNode` | 1 | `float` |
| `UC1_SVM_PROB` | `vtkMRMLVectorVolumeNode` | 4 | `float` |
| `UC1_KNN_PROB` | `vtkMRMLVectorVolumeNode` | 4 | `float` |

#### Translation into the canonical names

`SLIAFlowLogic.normalizeReceivedProvenance` is the single place that reconciles
the two spellings, and it runs before every discovery call. For each of the
five keys it accepts the prefixed spelling and the bare one, and the prefixed
value wins when both are present, because a bare value can only be a copy an
earlier message left behind.

The translation mirrors the wire rather than accumulating from it. The
connector updates one MRML node in place, message after message, so for a node
whose producer speaks the prefixed dialect a canonical attribute whose prefixed
counterpart is absent is removed rather than left standing. Otherwise a value
written for an earlier message would go on vouching for data that no longer
declares it, which is the same defaulting this contract forbids arriving by a
slower route. Nodes carrying no prefixed attribute at all are left alone: for
them the canonical name is the wire name and there is nothing to mirror.

One gap is upstream and cannot be closed here. The connector writes the keys a
message carries and removes none, so if a producer sends provenance once and
then stops sending it, the prefixed attributes from the earlier message remain
on the node and SLIAFlow has no way to tell that the latest frame did not carry
them. Producers must therefore send all five keys with every message. The
stand-ins do.

Accepting the bare spelling costs one line and is not currently exercised by
any build; it is there so that the receiver keeps working if the pin moves to a
build that behaves differently.

Discovery, validation and the SLIA-010 origin gate read only the canonical
`SLIAFlow.*` names and have no knowledge that a network exists. The received
node is the one node SLIAFlow does write to, and only these five attributes:
its image data, its name and its orientation are never touched.

A received node whose provenance is absent or unrecognized after translation is
reported invalid rather than shown, and rather than reported as a source that
has not arrived. A node that declares no provenance attribute at all makes no
claim and keeps the ordinary waiting state, so an unrelated scene volume that
happens to share a device name is not announced as a broken UC1 result.

### Connectors, states, and what a disconnection means

SLIAFlow owns two client connectors and creates neither until the operator asks
for it:

| Link | Endpoint | Devices |
| --- | --- | --- |
| Acquisition | `127.0.0.1:18944` | `LiveView` |
| UC1 | `127.0.0.1:18945` | the five map devices above, and `UC1_RGB` |

Both connector nodes carry `SLIAFlow.Owner = Connectors` and
`SaveWithScene = false`. Only a node carrying that ownership is ever stopped
and removed, so a connector created from the OpenIGTLinkIF panel is left alone.
Leaving the module, closing the scene and module cleanup all stop both.

The panel reports one of five states per link. `disconnected`, `connecting` and
`receiving` are translations of the connector's own `StateOff`,
`StateWaitConnection` and `StateConnected`. `displaying` and `invalid` are
stronger claims about what was made of the data, and the result path may use
either one only while the connector itself reports `StateConnected`. A valid
or invalid node retained in the scene cannot turn `StateOff` into
`displaying`/`invalid`, and `StateWaitConnection` remains `connecting` during
refreshes.

For an active OpenIGTLink client, a peer loss normally changes the connector
from `StateConnected` to `StateWaitConnection` while it retries. It reaches
`StateOff` when the connector is stopped. Therefore an automatically retrying
link is expected to show `connecting`, not `disconnected`, after the
disconnection event has been processed.

A lost connection is not a reason to blank a pane that is showing an image that
really did arrive and really did validate. The pane keeps that image and the
status says it is no longer being updated. A pane that never held a valid image
returns to black with its waiting message.

The live pane accepts either the laptop camera or the received `LiveView`
stream, and switching between them releases the source being left rather than
leaving it feeding a pane that no longer shows it: the camera is stopped, and
the reference to the received stream is dropped. The two sources are released
differently because they are owned differently. The camera belongs to the pane
and is torn down with it; the link belongs to the operator, who opened it with
its own button, so changing which source the pane shows releases the pane, not
the connection. A frame arriving while the camera is selected reaches no view.

`displaying` and `invalid` are claims about a live link, so neither is reported
unless the connector reports `StateConnected` and the current connection has
delivered the node being presented. The received node stays in the scene after
a link drops and is rediscovered by every later refresh, but rediscovery is not
news from the wire. Reconnection reports `receiving` and keeps the retained
image stale until a changed received node proves that the new socket has
delivered data. `LiveView` carries no
`SLIAFlow.ResultMap`, is never discoverable as a result, and is bound only to
the live pane; the UC1 result contract does not apply to it, but nothing
reaches a view before it is known to be displayable.

### Provenance never travels with the endpoint

SLIAFlow must never infer `simulated` from a port or a hostname. A stand-in and
the real application use the same port; the difference between them is what the
metadata says, and nothing else.

## Result device names

These are the five exact device names for the five map roles, on
`127.0.0.1:18945`:

| Map role | Device name |
| --- | --- |
| `tmdMap` | `UC1_TMD` |
| `majorityVotingMap` | `UC1_MV_CLASS` |
| `majorityVotingProbabilityMap` | `UC1_MV_PROB` |
| `svmProbability` | `UC1_SVM_PROB` |
| `knnProbability` | `UC1_KNN_PROB` |

`SLIA-012` first sent all five from a CUDA-free arithmetic stand-in, to prove the
producer/consumer seam before `SLIA-013` connected the genuine binary. `SLIA-025`
retired that stand-in, so today the genuine runner is the only map producer.

## SLIA-013 genuine UC1 runner

The genuine pipeline is connected by `tools/simulators/stratum_sim/uc1_runner.py`,
which builds nothing of its own: it runs the vendored UC1 binary, compiled
unmodified, and reads back what that binary wrote. It listens on
`127.0.0.1:18945` and implements the `Classifier` seam in `contract.py`.

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
being handed a fabricated one.

### Wire metadata the real runner stamps

| Key | Value |
| --- | --- |
| `SLIAFlow.ResultMap` | `majorityVotingMap` |
| `SLIAFlow.DeviceName` | `UC1_MV_CLASS` |
| `SLIAFlow.DataOrigin` | `simulated` |
| `SLIAFlow.SimulationDetail` | `real UC1 pipeline, recorded HSI case <case> (simulated acquisition)` |
| `SLIAFlow.CaptureId` | the run's capture ID, also on `UC1_RGB` when it is sent |

The origin is `simulated` even though the algorithm is genuine, and that is the
point of `SimulationDetail` carrying the distinction. A genuine algorithm run
over a recorded cube whose acquisition was simulated is not a genuine clinical
result, so the origin describes the acquisition and the detail describes the
producer and the input. Header version 2 applies
here for the same reason it applies everywhere else: at version 1 all five keys
are silently dropped.

### Recovering the class map

The binary emits colour, not classes, so the class map is recovered by inverting
the palette. The forward table and the inverse SLIA-013 reads with are one
definition in `bmp.py`, exported both ways, so they cannot drift apart. An RGB triple that is not in the table is reported with its count
and first offending coordinates and fails the run; it is never resolved to the
nearest known colour, because a nearest-colour fallback would turn an unexpected
pipeline output into a plausible-looking class map.

Outputs are checked for freshness rather than existence. UC1 writes the same
three `output/rgb/*.txt` names for every dataset on every run, so an existence
check cannot distinguish this run's output from a previous run's, and a crashed
run that left last week's files behind would pass one. A file that predates the
run fails it.

`docs/development/uc1_local_build.md` records the build, the measured runtime and
VRAM, and why a map can come back as a single class.

### The input is part of the provenance

Every cube is a recorded case of the public, anonymized HSI Human Brain Database
(`SLIA-023`), and every stream names what produced a message:

| Stream | Detail |
| --- | --- |
| `LiveView` | `acquisition stand-in, laptop camera`, which names the camera and never the case |
| `HSCube` | `acquisition stand-in, recorded HSI case <case> (simulated acquisition)` |
| `UC1_RGB`, `UC1_MV_CLASS` | `real UC1 pipeline, recorded HSI case <case> (simulated acquisition)` |

A recorded case is always described as one. A detail that did not name the case
would leave a viewer to guess what is on screen.

The runner reads the case from the folder itself - a folder is a recorded case
only when its `gtMap.hdr` carries the database marker - not from a flag, so the
detail cannot disagree with the data that was read, and any other folder is
refused. `DataOrigin` stays `simulated` in every case: in this repository the
acquisition is always simulated, and the origin never softens because the
algorithm is genuine or the cube was recorded.

A consumer must not branch on the detail. It is display-only and free text:
SLIAFlow reads it to write the second banner line and for nothing else.

## SLIA-024 cube-derived background

`UC1_RGB` is the background the class map is composited over, under
`docs/architecture/decisions/ADR-0001-overlay-result-on-cube-derived-rgb.md` and
`docs/architecture/decisions/ADR-0002-uc1-background-capture-identity-and-mismatch.md`.
It is not a result and has no result role.

| Device | MRML class | Components | Scalar type | Shape on the wire |
| --- | --- | ---: | --- | --- |
| `UC1_RGB` | `vtkMRMLVectorVolumeNode` | 3 | `unsigned char` | `(1, lines, samples, 3)`, the class map's `(k, j, i)` plus components |

Wire metadata: `SLIAFlow.DeviceName = UC1_RGB`, and `SLIAFlow.DataOrigin`,
`SLIAFlow.SimulationDetail` and `SLIAFlow.CaptureId` equal to those of the
`UC1_MV_CLASS` it accompanies.

`SLIAFlow.CaptureId` is an opaque value, one per classification of one cube. It is
never reused for another cube or another classification, and a resend of a
result already computed reuses it. The genuine runner makes one random value per
run and sends it in every cycle, on the map and on `UC1_RGB` when it is sent. It identifies nothing to a person. It
exists so that a `UC1_RGB` retained in the scene from another run - same device,
origin, detail and size - cannot be composited under a later map.

It is required on maps sent without a background, too. The OpenIGTLink connector
reuses one node per device name and sets each incoming key on it, but never
removes a key a later message omits. A map sent without an ID would keep the
previous run's ID, and match that run's retained `UC1_RGB`. SLIAFlow sees only
the node, so it cannot detect the omission. The guarantee rests on producers
sending the ID.
There is no `SLIAFlow.ResultMap`, so no discovery path can mistake it for a
result. The genuine runner sends it on the UC1 connection, before the map, in
every cycle. How it is assembled is in `tools/simulators/README.md`.

### The background layer

After the class map has passed validation and been presented, SLIAFlow looks for
a background. It is used only when all of these hold:

1. the map on screen is `majorityVotingMap`;
2. a received node declares device `UC1_RGB` exactly - or, declaring no device,
   is named `UC1_RGB` - is not owned by SLIAFlow, and has no result role;
3. the map's source node carries a non-empty `SLIAFlow.CaptureId`, and this node
   carries the same one. Among several candidates, only the one with the map's
   capture ID is considered, whatever order they arrived in;
4. it is a three-component `uint8` vector volume;
5. its `SLIAFlow.DataOrigin` and `SLIAFlow.SimulationDetail` are identical to the
   map's source node, compared on the full untruncated values;
6. its image dimensions are identical to the map's.

The image is then copied into the module-owned `SLIAFlow UC1 Background` node
(`SLIAFlow.Owner = ResultBackground`, not saved with the scene), which is bound to
the delineation panel's background slot, with the map in the foreground at the
layer's opacity.

### What is not done

- **No registration, resampling, reorientation or alignment.** A background that
  fails check 6 is refused, never fitted. Check 6 is the only geometric check.
- **No background is ever a precondition.** When any check fails, the map is
  bound exactly as it is without a background, and the panel's **Background**
  line states which check failed; for a size mismatch it names both sizes. A
  size mismatch is not shown side by side: the background is not displayed
  anywhere (`ADR-0002`, superseding that part of `ADR-0001` rule 4, once
  accepted).
- **No camera image, ever.** The laptop camera volume is owned by SLIAFlow and a
  `LiveView` stream declares its own device, so both fail check 2 under any node
  name. Discovery never considers a volume because it is an RGB image.
- **No background without its map.** A `UC1_RGB` that arrives while no valid map
  is displayed is not shown; the panel keeps its waiting state and banner rules.

## Validation and ownership

Before any result is assigned to the result slice view, SLIAFlow checks the
node type, positive image dimensions, component count, VTK/NumPy scalar type,
finite values, probability range, and class values. Validation has no MRML
side effects. Invalid or missing data clears the result view and reports a
waiting/invalid status.

Provenance and validation are orthogonal. Simulated data passes through the
identical checks and produces the identical messages, so a malformed simulated
map is rejected exactly as a malformed genuine one is.

The external source node is never deleted, and the only change SLIAFlow makes
to it is writing the five canonical provenance attributes translated from the
wire names it arrived with. Its image data, name and orientation are left
exactly as received. SLIAFlow owns a transient scalar display volume for scalar maps and selected SVM/KNN channels,
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
