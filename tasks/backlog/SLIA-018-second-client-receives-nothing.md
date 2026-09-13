---
id: SLIA-018
title: Warn when a second client is attached and receiving nothing
status: backlog
branch:
priority: high
depends_on: SLIA-011, SLIA-012, SLIA-013
required_skills: []
optional_tools: []
related_adrs: []
---

# SLIA-018 - Warn when a second client is attached and receiving nothing

## Goal

Make a producer say out loud that it has more than one client attached, so that
the second client's empty panes are attributable to the transport rather than
looking like a broken module.

## Context

Found while re-running the SLIA-014 session on the project owner's report that
the pipeline "is not working". Every automated suite passed - 110 simulator
tests, 45 Slicer tests, Ruff on both targets - and the rig came up correctly.
The cause was a Slicer left running from an earlier session.

`pyigtl.OpenIGTLinkServer` inherits `socketserver.TCPServer`, not its threading
variant, and `TCPRequestHandler.handle()` loops for the life of the connection.
So the server accepts and serves exactly one client at a time. A second client's
handshake is completed by the kernel from the listen backlog, which means:

- the second client's socket is genuinely `ESTABLISHED`;
- `OpenIGTLinkClient.is_connected()` returns `True` for it;
- `Get-NetTCPConnection -State Established` counts it;
- and it receives nothing at all until the first client lets go.

Measured directly against `pyigtl` 0.3.4, with a producer sending at 20 Hz:

| Client | State | Messages received in a 4 s window |
| --- | --- | --- |
| A, attached first | connected | 20 of 20 polls |
| B, attached second | connected | 0 of 20 polls |
| B, after A disconnects | connected | 20 of 20 polls |

An operator who leaves a Slicer open from a previous session, then starts a new
session, sees the new Slicer report both links connected and both panes stay
empty for as long as the old process lives. There is nothing on screen, in
either Slicer or the producer log, that distinguishes this from a module that
has stopped working.

This is a transport and tooling property, not a SLIAFlow defect. SLIAFlow
behaved correctly: it opened both connections and displayed what arrived on
them, which was nothing.

The session launcher was given a preflight check under SLIA-014
(`Assert-NoStaleClients`) that refuses to start when another process is already
dialling 18944 or 18945, and a runtime warning when a port reports more than one
client. That covers the launcher's own path. It does not cover a client that
attaches mid-session, or anyone running the producers by hand.

### What the WP5 demonstrator changes about this

`docs/architecture/WP5_MS5_DEMO_PLAN.md` takes the rig to five bound ports, and
the launcher's preflight must grow with it. More importantly, the demonstrator
makes the symptom worse in a specific way: with six panels instead of two, a
second Slicer left open from an earlier session does not blank one pane, it
blanks four. An operator sees a screen that is almost entirely black, with every
link reporting connected, and nothing anywhere naming the cause.

The plan also records why multiplexing is not the fix and should not be reached
for: `pyigtl.OpenIGTLinkServer`'s send queue belongs to the server rather than to
the connection, so **even a `ThreadingMixIn` would not fan a message out** - each
message would still leave over one connection. A real fan-out needs per-connection
queues written by us, which is Mode B work and out of scope here. In Mode A the
algorithms read the announced folder from disk, so nothing needs it.

This card stays a diagnostic.

## Requirements

- Each producer reports the number of clients it is actually serving, and says
  so when that number changes.
- When a connection is accepted while another is already being served, the
  producer logs a warning that names the condition: the new client will receive
  nothing until the incumbent disconnects.
- The warning states the remedy - close the other client - and does not claim
  the second client is disconnected, because it is not.
- The wording must not suggest the producer is at fault or that data was lost.

## Out of scope

- Making the producers serve several clients at once. Multiplexing a live stream
  to several receivers is a behaviour change, not a diagnostic, and the
  hardware-free architecture does not need it.
- Changing `pyigtl`, or vendoring a patched copy of it.
- Any change to SLIAFlow. What the panel reports about a starved-but-open link
  is close to SLIA-016 but not the same defect: there the socket is dead, here
  it is genuinely established.

## Files allowed

- `tools/simulators/stratum_sim/**`
- `tools/simulators/tests/**`
- `tools/simulators/README.md`
- `docs/development/pipeline_test_quickstart.md`
- `tasks/{backlog,active,review,completed}/SLIA-018-second-client-receives-nothing.md`

## Relevant skills and references

- `pyigtl.comm.OpenIGTLinkServer` and `TCPRequestHandler.handle`
- `socketserver.TCPServer` versus `ThreadingTCPServer`
- `scripts/development/run-end-to-end-session.ps1`, `Assert-NoStaleClients`
- SLIA-017, which is the mirror of this on the producer side: two servers on one
  port, rather than two clients on one server

## Approved dependencies

None. The connection count is available from the server object.

## Reproduction

1. Start either UC1 producer on 18945.
2. Connect a client and leave it connected.
3. Connect a second client to the same port.
4. Poll the second client for messages.

Observed: the second client reports itself connected and receives nothing, and
the producer log is indistinguishable from a healthy single-client session.
Expected: the producer says a second client is attached and is being starved.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| A second concurrent client produces a warning | New unit test attaching two clients to one producer | automated |
| A single client produces no warning | Existing coverage, unchanged | automated |
| A client attaching after the first has left produces no warning | New unit test | automated |

The first test fails against the current code because nothing is logged.

## Manual verification

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Run the reproduction above | The producer names the second client and says it will receive nothing until the first leaves | |
| 2 | Start a session with a Slicer from an earlier session still open | The launcher refuses before starting anything, naming the process | |

## Risks

The count must come from the server's own accepted connections rather than from
a socket table, or the warning will fire on a connection the producer has not
accepted and cannot describe. A warning that cries wolf on an ordinary
reconnection is worse than no warning, because the operator learns to ignore it.

## Documentation impact

- `docs/development/pipeline_test_quickstart.md`: the troubleshooting table gains
  the two-clients row; it is the single most likely reason a session looks dead.
- `tools/simulators/README.md`: note that a producer serves one client at a time.

## Completion evidence

Reserved for implementation evidence.

## Review findings

Reserved for review.

## Human approval

Required before review and completion.
