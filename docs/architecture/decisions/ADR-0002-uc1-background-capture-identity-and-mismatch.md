---
id: ADR-0002
title: Enforce UC1 background capture identity, and show a mismatched map alone
status: accepted
date: 2026-09-16
accepted: 2026-09-16
related_tasks: SLIA-024
supersedes: ADR-0001 (rule 4 in part, and the first Validation bullet)
superseded_by: ADR-0003
---

# ADR-0002 - Enforce UC1 background capture identity, and show a mismatched map alone

## Status

Superseded in full by `ADR-0003`, accepted 2026-09-17: SLIAFlow no longer
composites a background, so there is no capture identity to enforce between two
images. The rule of one opaque capture ID per classification is kept in
substance by `ADR-0003` decision 5.

Accepted by the project owner on 2026-09-16, during `SLIA-024`.

Proposed on 2026-09-16, from the review of `SLIA-024` before manual
verification. The project owner chose both directions recorded here. The
owner's review of the first draft, the same day, made the capture ID mandatory on
every UC1 map and stated what the consumer can and cannot enforce.

Applied at acceptance: `ADR-0001`'s front matter gained
`superseded_in_part_by: ADR-0002`, and `ADR-0001`'s rule 4 and first Validation
bullet each gained a note that this ADR replaces them. Every other rule of
`ADR-0001` stands unchanged.

## Context

`ADR-0001` permits a result to be composited only over a background derived from
its own cube. Rule 3 makes "same capture" a property of the transport: one
producer sends `UC1_RGB` and `UC1_MV_CLASS` on one connection. Rule 4 makes a
size comparison the only geometric safeguard and says mismatched images are
"shown side by side with an explicit status".

The `SLIA-024` implementation and its review exposed two gaps.

**Rule 3 holds on the wire but not in the scene.** SLIAFlow sees MRML nodes,
not messages or connections. OpenIGTLinkIF's `vtkMRMLIGTLConnectorNode` reuses
one node per device name, and for each incoming message it sets every metadata
key the message carries on that node as `OpenIGTLink.<key>`. It never removes a
key that a later message omits. A node therefore describes the union of every
message ever received under its device name, not the latest one.

Two consequences follow:

- A `UC1_RGB` from an earlier run stays in the scene after that run ends. If a
  later run sends a map and no background (the arithmetic stand-in always does
  this, and so does the genuine runner when it refuses the bands), the retained
  background still has the device name, and can have the same origin, the same
  simulation detail and the same dimensions as the new map. Every check before
  this ADR would pass, and a class map would be drawn over a capture it was not
  computed from. That is the failure `ADR-0001` exists to prevent, and a viewer
  cannot see it. With several `UC1_RGB` nodes in the scene, "the first one found"
  is also arbitrary.
- An identifier cannot be optional. If a map carrying no identifier arrives on
  a node that held a map with one, the node keeps the old identifier, and that
  identifier matches the old run's retained background. SLIAFlow cannot tell a
  value the current message carried from one an earlier message left behind.

`WP5_MS5_DEMO_PLAN.md` said "No capture identifiers, no extra protocol". That was
reasoned from the transport alone, before the retained-node case was found.

**Rule 4's side-by-side presentation has nowhere to go.** The operator surface is
six fixed panels, each with its own role: LiveView, Stereoscopic, HS Cube,
Relative StO2, Enhanced Vascularization and Tumour Delineation. Showing the
background beside the map means taking another panel's place or changing the
layout. The runner already refuses to send a background whose shape differs from
the map's, so the consumer's size check is a backstop that the genuine producer
should never reach.

## Decision

1. **Every UC1 result map carries a capture ID.** Every map a UC1 producer
   sends carries a non-empty `SLIAFlow.CaptureId`, whether or not a background is
   sent. If a `UC1_RGB` is sent, it carries the same ID as the map it
   accompanies. A producer that sends no background, the arithmetic stand-in
   included, still sends the ID on its maps. The contract's metadata builders
   refuse to build map or background metadata without one.
2. **Identity scope.** A capture ID is opaque and randomly generated. It
   identifies one classification of one input cube:
   - a new classification, or a different input cube, gets a new ID, and an ID
     is never reused for either;
   - a retransmission of a result already computed reuses that result's ID.

   The ID is independent of the connection, the resend cycle, the dataset name
   and the device name. Both current producers classify once per run and resend
   the result every cycle, so each makes one ID per run.
3. **Consumer rule.** SLIAFlow composites a map over a `UC1_RGB` **only** when
   both nodes carry the same non-empty `SLIAFlow.CaptureId`, and the origin,
   detail, format and size checks also pass. A map node with no capture ID is
   never composited. Among several `UC1_RGB` nodes, the one whose capture ID
   matches the map's is the candidate; the rest are ignored.
4. **Mismatch presentation (replaces the presentation in `ADR-0001` rule 4).** If
   the matching background and the map do not have the same dimensions, they are
   not composited. The map is displayed alone, exactly as it is when no
   background has arrived, and an explicit status names both sizes. The
   background is not displayed anywhere.

What rule 4 forbids is unchanged: SLIAFlow performs no registration, resampling
or alignment, and never makes two mismatched images agree.

### What the consumer can enforce

SLIAFlow compares the attributes on persistent nodes. It enforces decision 3 on
those nodes and nothing more. It cannot detect that the latest message on a
device omitted the capture ID, because the connector leaves the previous value in
place.

The guarantee that a background is never composited under a map from another
classification therefore rests on two things together:

- producers sending a fresh ID on every map, as decisions 1 and 2 require, so
  that each new map overwrites its node's previous ID;
- SLIAFlow requiring an exact match, as decision 3 requires.

A producer that breaks decision 1 is outside the contract, and SLIAFlow cannot
detect it. Changing this, by clearing omitted metadata in the connector or by
exposing per-message metadata to SLIAFlow, would be a different decision.

## Rationale

The capture ID turns "same capture" from an inference into an identity. The
inference was same device name, same metadata and same size, and a node retained
from another classification cannot share the identity. It is the smallest
addition that closes the gap: one opaque string, compared for equality, carried
in the metadata the contract already has. It does not need to identify a capture
globally or mean anything to a person. It only has to differ between
classifications.

Mandatory on every map, rather than only when a background is sent, because
only a value that is always present is always overwritten. That makes a stale
match structurally impossible for conforming producers, without relying on the
connector removing anything.

Per classification rather than per resend, because a per-cycle value would
describe a resend, not a capture. It would also leave the map alone for no reason
whenever a refresh landed between one cycle's background and its map.

Showing the map alone on a mismatch is the more conservative reading once there
is no panel to show both:

- It is what the operator already sees when no background arrives, so a mismatch
  cannot look like a new, unexplained state, and the status line says what
  happened.
- It preserves the fixed six-panel layout and displaces no other view.
- It never puts two images that must not be read against each other next to each
  other, in a way that invites exactly that reading.

## Alternatives considered

**Implement side by side as written.** Rejected for now: it needs a layout
change or borrows a panel with its own role, for a path the genuine producer
cannot reach.

**Make the capture ID optional for producers without a background.** Rejected
on review: the connector never removes an attribute a later message omits, so a
map without one keeps the previous run's ID and matches that run's retained
background.

**Clear omitted metadata on the connector, or read per-message metadata.** Not
chosen: it means changing or working around OpenIGTLinkIF behaviour, which this
project does not own, when a mandatory producer field closes the same gap.

**Judge capture by arrival order** - accept a `UC1_RGB` only if it arrived after
the previous map update. No wire change, but it depends on the connector's event
timing and the refresh throttle, and it cannot tell two runs apart once both
nodes exist.

**Record the stale-background risk and change nothing.** Rejected: that leaves in
place the convincing but wrong overlay that `ADR-0001` is written to prevent.

## Consequences

- `SLIAFlow.CaptureId` is added to the UC1 contract (`contract.py`, the image
  contract document) as required metadata on every UC1 map, and on `UC1_RGB`
  when it is sent. `contract.newCaptureId` makes one.
- The arithmetic stand-in generates a capture ID per run and sends it on all five
  maps, although it sends no background.
- SLIAFlow's provenance translation carries the new key like the other four.
- The `WP5_MS5_DEMO_PLAN.md` line "No capture identifiers, no extra protocol" is
  corrected.
- A stand-in map is never composited over a genuine runner's background, even on
  the same case.
- A producer outside this repository that sends UC1 maps must send the ID too.
  Otherwise its maps can inherit an ID left on the node by an earlier producer.

## Validation

- An automated test asserts that a background whose capture ID differs from the
  map's, or a map without one, is not composited, even when origin, detail and
  size all match.
- An automated test asserts that, among several `UC1_RGB` nodes, the one matching
  the map's capture ID is composited.
- An automated test asserts that a map-only run following a map-plus-background
  run is shown alone. The map arrives on the node that held the earlier map, with
  a new capture ID, and the earlier `UC1_RGB` is retained with matching origin,
  detail and size.
- Automated tests assert that the contract refuses to build map or background
  metadata without a non-empty capture ID. Further tests assert that the runner,
  with and without a background, and the stand-in each send one ID on every
  message of a run, and a different one on the next run.
- An automated test asserts that a result and a background of different
  dimensions are not composited, that the map is displayed alone, and that the
  status names both sizes. This replaces `ADR-0001`'s first Validation bullet.

## Related tasks

- `SLIA-024` - implements both rules.

## Superseded ADRs

- `ADR-0001`, in part: the presentation in rule 4 ("shown side by side") and the
  first Validation bullet. Rules 1 to 3, 5, the rest of rule 4 and the other
  Validation bullets stand.
