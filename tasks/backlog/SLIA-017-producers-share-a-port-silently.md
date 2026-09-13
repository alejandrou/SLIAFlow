---
id: SLIA-017
title: Refuse to start a producer on a port another producer already holds
status: backlog
branch:
priority: medium
depends_on: SLIA-011, SLIA-012, SLIA-013
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-017 - Refuse to start a producer on a port another producer already holds

## Goal

Make a stand-in or runner fail loudly when the port it is asked to serve is
already being served, instead of binding alongside the incumbent and leaving the
client to reach whichever one happens to accept.

## Context

Found while setting up the SLIA-014 end-to-end session. Three processes were
found listening on `127.0.0.1:18945` at the same time - a genuine UC1 runner, an
arithmetic stand-in left over from an earlier run, and a third - and the Slicer
connector was connected to none of the two that were meant to be there.

`pyigtl.OpenIGTLinkServer` inherits `socketserver.TCPServer` with
`allow_reuse_address = 1`, which sets `SO_REUSEADDR`. On Linux that only relaxes
`TIME_WAIT`. On Windows it does something else entirely: it lets a second socket
bind an address another socket is actively listening on, and incoming
connections go to one of them by rules the application does not control. So a
producer started on an occupied port neither fails nor takes over. It joins.

That matters here more than it would in most projects, because the whole
hardware-free architecture rests on one property: stopping one producer and
starting another on the same port changes what SLIAFlow displays. An operator
following the SLIA-014 procedure who does not notice that the first producer is
still alive can watch a swap appear to fail, or worse appear to succeed while
the data still comes from the old producer. The banner would then be the only
thing telling the truth, and only because it travels with the data.

This is a stand-in and tooling defect, not a SLIAFlow defect. SLIAFlow behaved
correctly throughout: its display followed the data on the connection it had.

## Requirements

- Before binding, each producer entry point checks whether the port is already
  being served and exits with a clear error naming the port and, where it can be
  determined, the process holding it.
- The check covers every producer entry point that binds a fixed port: the
  acquisition stand-in, the UC1 arithmetic stand-in, the genuine UC1 runner, and
  the `HSCube`, `Control` and UC2 producers added by `SLIA-023` and `SLIA-021`.
- No producer binds a reserved port. 18948 and 18949 stay unbound, and a producer
  asked to serve one refuses by name rather than by the generic occupied-port
  message.
- The error says what to do: stop the other producer, or pass a different port.
- An explicit override exists for the case where sharing is genuinely wanted,
  and it is off by default.

### What the WP5 demonstrator changes about this

`docs/architecture/WP5_MS5_DEMO_PLAN.md` takes the rig from two ports to seven:
18944 `LiveView`, 18945 `UC1_MV_CLASS` and `UC1_RGB`, 18946 `UC2_BV`, 18947
`HSCube`, 18950 `Control`, with 18948 and 18949 reserved and deliberately unbound.
Every one of them is a fixed port bound by a producer entry point, so the failure
mode this card describes becomes roughly three times more likely to be met per
session, and one of the seven - 18945, which now carries two device names from one
producer - is the port where a silent second listener would be hardest to spot.

Two consequences for this card's scope. The check covers every producer entry
point rather than the three named below, including the ones `SLIA-023` and
`SLIA-021` add. And **a producer must never bind a reserved port**: 18948 and
18949 carry a promise that nothing is listening, and a black panel that is black
because a stray producer took the port is indistinguishable from one that is
black for the right reason.

## Out of scope

- Changing `pyigtl`, or vendoring a patched copy of it.
- Any change to SLIAFlow.
- Port allocation policy. The seven ports stay what
  `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` says they are.

## Files allowed

- `tools/simulators/stratum_sim/**`
- `tools/simulators/tests/**`
- `tools/simulators/README.md`
- `docs/development/end_to_end_verification.md`
- `tasks/{backlog,active,review,completed}/SLIA-017-producers-share-a-port-silently.md`

## Relevant skills and references

- `docs/development/end_to_end_verification.md`, the prerequisites table and its
  free-port check
- `pyigtl.comm.OpenIGTLinkServer` and `socketserver.TCPServer.allow_reuse_address`

## Approved dependencies

None. The check is a standard-library socket probe.

## Reproduction

1. Start any producer on 18945 and leave it running.
2. Start a second producer on 18945.
3. `netstat -ano | findstr 18945`.

Observed: both processes appear as `LISTENING` on the same address, and the
second producer prints its ordinary startup banner as though it owned the port.
Expected: the second producer exits with an error.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A producer refuses an occupied port | New unit test binding a socket first, then invoking the entry point | automated |
| A producer starts normally on a free port | Existing coverage, unchanged | automated |
| The override still allows a deliberate second bind | New unit test | automated |

The first test fails against the current code because the second bind succeeds
on Windows.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the reproduction above | The second producer exits with a message naming port 18945 | |
| 2 | Run the SLIA-014 producer swap with the first producer deliberately left running | The swap is refused rather than silently producing two listeners | |

## Risks

A port check is a race by nature: the port can be taken between the probe and
the bind. The check is a guard against the common mistake, not a lock, and the
error message should not claim more than that.

## Documentation impact

- `docs/development/end_to_end_verification.md`: the prerequisites free-port
  check becomes advisory once the producers enforce it themselves, and the
  finding that motivated this card is already recorded there.
- `tools/simulators/README.md`: note the refusal and its override.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
