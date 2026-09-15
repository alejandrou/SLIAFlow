---
id: SLIA-018
title: Warn when a second client is attached and receiving nothing
status: completed
branch: feature/SLIA-018-second-client-receives-nothing
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

### What activation measured, and the decision it forced

Measured on 2026-09-14 against the installed `pyigtl` 0.3.4 (distribution
metadata; `pyigtl.__version__` still reports 0.3.2), on Windows 11, with scratch
probes that are not part of the change.

The card originally said the warning should fire "when a connection is accepted
while another is already being served", with the count taken "from the server's
own accepted connections rather than from a socket table". Neither is possible
as written. `socketserver.TCPServer.serve_forever` calls `handle()` on its own
thread and does not call `accept()` again until `handle()` returns, so the
second connection is **never accepted**. The server's accepted count is 0 or 1
by construction and cannot see the client this card is about.

What the server does own is its listening socket, and a queued connection makes
it readable (`select`) without being accepted:

| Situation | Listening socket readable | Server-side TCP row of the queued connection |
| --- | --- | --- |
| One client, served | no | - |
| Second client attached and waiting | yes, for as long as it waits (still true after 3 s of 20 Hz streaming) | `ESTABLISHED` |
| First client left, replacement attached, producer sending every 0.05 s | yes, clears in 0.05 s | `ESTABLISHED` |
| Same, producer sending every 1.0 s (the UC1 interval) | yes, clears in 1.01 s | `ESTABLISHED` |
| Same, producer sending nothing (the `HSCube` port between captures) | yes, indefinitely | `ESTABLISHED`; the departed client's row is `CLOSE_WAIT` |
| Waiting client closed gracefully before being served | **yes, indefinitely** | `CLOSE_WAIT` |
| Waiting client reset (abortive close) before being served | **yes, indefinitely** | no row |

The last two rows are the problem. On Windows a connection that gave up while
queued stays queued, so a check on the listening socket alone would warn about
a second client that no longer exists, for as long as the first one is served -
exactly the warning that cries wolf this card's risk section forbids. The TCP
table tells the cases apart: a client that is really still attached has an
`ESTABLISHED` row; one that has gone does not.

The project owner decided on 2026-09-14: **the server's own listening socket
raises the alarm, and the TCP table confirms it.** The warning fires only when a
connection has stayed queued past a grace period and the table shows at least
two `ESTABLISHED` connections on the producer's own port, owned by the producer's
own process. Reading the table costs about 13 ms through `netstat`, and less
through the IP Helper API used here.

## Requirements

- Every producer that serves a port through `igtl_transport.ImageStreamServer`
  gets the diagnostic without a change to its own loop: the acquisition
  stand-in's LiveView, HSCube and Control ports, the UC1 arithmetic stand-in and
  the genuine UC1 runner, and any later producer built on the same class.
- The producer reports the number of clients it is actually serving, and prints
  a line when that number changes:
  - `127.0.0.1:<port>: serving 1 client.`
  - `127.0.0.1:<port>: serving 0 clients.`
- When a connection has stayed queued behind the served client for at least
  `WAITING_CLIENT_GRACE_SEC` (2.0 s) and the TCP table confirms at least two
  `ESTABLISHED` connections on the producer's port owned by the producer's
  process, the producer prints once:
  `WARNING: 127.0.0.1:<port> has <n> clients attached, and a producer serves one client at a time. The client being served receives everything; every other attached client shows as connected and receives nothing until the one being served is closed. Close the other client - most often a Slicer left open from an earlier session.`
- When that confirmation no longer holds, the producer withdraws the warning
  once: `127.0.0.1:<port>: only one client is attached again; the warning above no longer applies.`
- The warning states the remedy, does not claim the second client is
  disconnected, and does not suggest the producer is at fault or that data was
  lost: it contains none of `disconnected`, `lost`, `fault`, `error`, `fail`.
- The grace period is longer than the slowest measured release of a departed
  client by a sending producer (1.01 s at the 1.0 s UC1 interval), so an
  ordinary reconnection does not warn even before the table is consulted.
- A served client that closes its connection is let go within one pyigtl read,
  whether or not the producer is sending, so a client queued behind it is served
  and receives the next message. pyigtl on its own lets a client go only when a
  send to it fails, which on the `HSCube` port between captures meant never:
  the replacement was starved and the next cube was queued for the closed
  connection. Added by the project owner on 2026-09-14; see Human approval.
- Lines go to standard output, flushed, because that is the stream the session
  launcher tails with the producer's tag. Standard error is shown only when a
  producer exits.
- The TCP table is read with the standard library (`ctypes` over
  `iphlpapi.GetExtendedTcpTable`), which is locale-independent, unlike parsing
  `netstat` text. Where the table cannot be read - not Windows, or the call
  fails - no warning is confirmed; the attach and release lines still print.
- Starting, stopping and the existing send-failure restart of the server start
  and stop the watch with it, and `stop()` never hangs or raises because of it.

## Out of scope

- Making the producers serve several clients at once. Multiplexing a live stream
  to several receivers is a behaviour change, not a diagnostic, and the
  hardware-free architecture does not need it.
- Changing `pyigtl`, subclassing its request handler, or vendoring a patched
  copy of it. `ImageStreamServer` does subclass the server, to add one check
  before pyigtl's own read; see the requirement on a client that closes.
- Any change to SLIAFlow. What the panel reports about a starved-but-open link
  is close to SLIA-016 but not the same defect: there the socket is dead, here
  it is genuinely established.
- The launcher. Its preflight and runtime warning stay as SLIA-014 left them.
- Two producers bound to one port, which is `SLIA-017`.

## Files allowed

- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/tests/test_igtl_transport.py`
- `tools/simulators/README.md`
- `docs/development/pipeline_test_quickstart.md`
- `tasks/{backlog,active,review,completed}/SLIA-018-second-client-receives-nothing.md`

## Relevant skills and references

- `pyigtl.comm.OpenIGTLinkServer` and `TCPRequestHandler.handle` in the
  installed 0.3.4
- `socketserver.TCPServer.serve_forever` versus `ThreadingTCPServer`
- Windows IP Helper `GetExtendedTcpTable` with `TCP_TABLE_OWNER_PID_ALL`
- `scripts/development/run-end-to-end-session.ps1`, `Assert-NoStaleClients` and
  `Show-LinkState`
- SLIA-017, which is the mirror of this on the producer side: two servers on one
  port, rather than two clients on one server

## Approved dependencies

None. `ctypes`, `select` and `threading` are standard library.

## Reproduction

1. Start either UC1 producer on 18945.
2. Connect a client and leave it connected.
3. Connect a second client to the same port.
4. Poll the second client for messages.

Observed: the second client reports itself connected and receives nothing, and
the producer log is indistinguishable from a healthy single-client session.
Expected: the producer says a second client is attached and is being starved.

## Implementation plan

1. Add the five tests below to `test_igtl_transport.py` and run them against the
   unchanged `igtl_transport.py`; record each failure.
2. In `igtl_transport.py`, add `establishedServerConnectionCount(port)`: the
   number of `ESTABLISHED` IPv4 rows whose local port is `port` and whose owning
   process is this one, or `None` when the table cannot be read.
3. Add a watch thread owned by `ImageStreamServer`, started in `start()` and
   stopped and joined in `stop()` before the pyigtl server closes. Every
   `CLIENT_WATCH_POLL_SEC` it reads `is_connected()`, checks the listening
   socket with a zero-timeout `select` while a client is served, and prints the
   attach, release, warning and withdrawal lines on transitions.
4. Run the new tests again, then run each guard test against the mutations named
   in the test plan, applied with `unittest.mock.patch` from a scratch runner so
   that no source file is edited to produce them, and record those failures.
5. Update the README's one-client note and the quickstart's troubleshooting row.
6. Run the full simulator suite, Ruff on both targets, and the Slicer suite.
7. Added by the owner's decision: add
   `test_aClientReplacingOneThatLeftReceivesTheNextMessage` and run it against
   the transport before the change; subclass `pyigtl.OpenIGTLinkServer` in
   `igtl_transport.py` so that `_receive_message_from_socket` peeks one byte
   first and raises on an empty peek, which ends pyigtl's handler as a failed
   send does; then repeat step 4 for the new test and step 6.

## Acceptance criteria

1. A producer prints `serving 1 client.` when a client is being served and
   `serving 0 clients.` when pyigtl lets it go, naming its host and port.
2. A second client attached while one is served draws, within the grace period
   plus polling, one `WARNING:` line naming the host, port and client count,
   stating that the others receive nothing until the served client is closed and
   that the other client should be closed, and containing none of
   `disconnected`, `lost`, `fault`, `error`, `fail`.
3. A single client draws no warning.
4. A client that replaces one that has left draws no warning, even when the
   producer sends nothing and has not yet noticed the departure.
5. When a waiting client leaves before being served, the warning is withdrawn
   and not repeated.
6. The lines reach the operator in the session launcher, tagged with the
   producer's name.
7. The existing simulator suite and Ruff pass with no existing test modified.
8. The README and the quickstart's troubleshooting table describe the warning.
9. A client that replaces one that has closed, on a port that sends nothing in
   between, is served and receives the next message sent.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Served count reported on change | `ClientWatchTest.test_theServedCountIsReportedWhenTheClientGoes`; manual steps 2 and 5 | automated, manual |
| 2. Second client warned about, correctly worded | `ClientWatchTest.test_aSecondAttachedClientIsWarnedAbout` | automated |
| 3. Single client draws no warning | `ClientWatchTest.test_aSingleClientDrawsNoWarning` | automated |
| 4. Replacement for a departed client draws no warning | `ClientWatchTest.test_aClientReplacingOneThatLeftDrawsNoWarning`; manual step 5 | automated, manual |
| 5. Warning withdrawn when the waiter leaves | `ClientWatchTest.test_theWarningIsWithdrawnWhenTheWaitingClientLeaves`; manual step 4 | automated, manual |
| 6. Lines reach the launcher console | Manual steps 2 to 5 | manual |
| 7. Existing suite and Ruff unchanged | `tools\simulators\tests\run_tests.py`, `run-python-quality.ps1` | automated |
| 8. Documentation describes the warning | Manual step 6 | manual |
| 9. Replacement served and sent the next message | `ClientWatchTest.test_aClientReplacingOneThatLeftReceivesTheNextMessage`; agent rehearsal on the `HSCube` port | automated, rehearsal |

Tests to add or change, and how each one will be shown to fail first:

- All five attach real `pyigtl.OpenIGTLinkClient`s to a real
  `ImageStreamServer` on a free local port and assert on what the producer
  prints to standard output, because that is what reaches the operator. They use
  the production grace period, so a failure against the unchanged code is an
  assertion about missing output rather than a missing parameter.
- `test_theServedCountIsReportedWhenTheClientGoes` and
  `test_aSecondAttachedClientIsWarnedAbout` fail against the unchanged code
  because nothing is printed.
- `test_theWarningIsWithdrawnWhenTheWaitingClientLeaves` fails against the
  unchanged code because no warning appears, and against a mutation that skips
  the TCP-table confirmation because the warning is never withdrawn - the queued
  connection stays visible after the waiter has gone.
- `test_aClientReplacingOneThatLeftDrawsNoWarning` fails against the unchanged
  code on its precondition (no `serving 1 client.` line). It also failed against
  the same no-table mutation until the close check of requirement "a served
  client that closes" existed; with that check the replacement is served before
  the grace period ends, so the mutation no longer reaches it, and
  `test_theWarningIsWithdrawnWhenTheWaitingClientLeaves` is the table's guard.
- `test_aClientReplacingOneThatLeftReceivesTheNextMessage` fails against the
  transport before the close check because the departed client is never let go,
  and against a mutation that restores pyigtl's own read for the same reason.
  No manual step covers it: the repository has no `HSCube` client for a person to
  run, so it is rehearsed with a scratch client instead.
- `test_aSingleClientDrawsNoWarning` fails against the unchanged code on its
  precondition. Its no-warning assertion is shown failing against a double
  mutation: the listening socket always reports a queued connection, and the
  table count is one too high. Corrected during implementation: the specification
  first named a single threshold mutation (confirming at one connection instead
  of two), but the table is consulted only while a connection is queued, and a
  single client never queues one, so that mutation cannot make a single client
  warn. Both guards have to fail together, which is what the double mutation
  does.
- The three tests that need the TCP table skip with a stated reason off Windows.
  This project runs on Windows 11, so a skip there is a failure to investigate.
- No existing test is modified.

## Manual verification

Run in PowerShell from the repository root. Recorded case `004-02` must be
present under `input\bin\bin`. Slicer is not needed. The launcher's own
`[status]` line also turns red when a port has two clients; that line is
SLIA-014's. The lines this card adds are tagged `[acq]`.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Shell 1: `.\scripts\development\run-end-to-end-session.ps1 -Case 004-02 -NoSlicer`. Wait for the rig to report LiveView listening on 18944. | The session came up and no `[acq]` line contained `WARNING:`. | Verified by the project owner; the clean launcher startup showed no warning. |
| 2 | Shell 2: `.\.venv\Scripts\python.exe tools\simulators\tests\liveview_client.py --frames 100000` | Shell 2 prints the LiveView metadata. Shell 1 shows `[acq] 127.0.0.1:18944: serving 1 client.` and no `WARNING:`. | Verified by the project owner; metadata and the single-client line appeared without a warning. |
| 3 | Shell 3: run the same command as shell 2. Watch shell 1 for five seconds. | Shell 3 prints `Connecting to 127.0.0.1:18944 ...` and no metadata. Within about three seconds shell 1 shows one `[acq] WARNING: 127.0.0.1:18944 has 2 clients attached ...` line telling you to close the other client. It does not say the second client is disconnected. | Verified by the project owner; the second client stayed empty and one correctly worded warning appeared. |
| 4 | Leave shell 3 alone until it gives up (about 10 s after it started). | Shell 3 prints `ERROR: no LiveView message arrived before the timeout.` and exits. Within about a second shell 1 shows `[acq] 127.0.0.1:18944: only one client is attached again; the warning above no longer applies.` No further `WARNING:` line follows while shell 2 keeps running. | Verified by the project owner; the second client timed out and the warning was withdrawn once. |
| 5 | Press Ctrl-C in shell 2, then start the same client again in shell 2. | Shell 1 shows `serving 0 clients.`, then `serving 1 client.` for 18944 again. No `WARNING:` line appears for the reconnection. | Verified by the project owner; release and reconnection were reported with no warning. |
| 6 | Read the "Only one client at a time" paragraph in `tools\simulators\README.md` and the "Both panes stay empty but the panel says connected" row in `docs\development\pipeline_test_quickstart.md`. | Both name the producer's `WARNING:` line and say what to do about it. | Verified by the project owner; both documents name the warning and the remedy. |
| 7 | Press `q` in shell 1. | The session stops cleanly with no hang. | Verified by the project owner; the session stopped cleanly with no held sockets. |

## Risks

The warning must never fire on a client that is not there. On Windows the
listening socket keeps a connection queued after the client behind it has given
up, which is why the TCP table confirms every warning. If the table cannot be
read, the producer stays silent rather than guessing.

A second producer sharing the port through `SO_REUSEADDR` (`SLIA-017`) would put
its own clients in the table. Counting only rows owned by this process keeps
them out of this producer's count.

The watch is a thread polling a socket that `stop()` closes, so
`ImageStreamServer.stop()` joins it before closing the pyigtl server. A client
leaving does not reach the send-failure restart path: `send_message(wait=False)`
only queues, and pyigtl handles the failed send on its own serving thread. A
socket closed under the watch anyway - pyigtl's own SIGINT handler does that -
ends the watch quietly instead of raising.

While a departed connection stays queued, the watch reads the TCP table on
every poll. Measured on the development laptop with 92 table rows, one read
takes 0.157 ms, so ten reads a second cost about 0.16 % of one core.

Every server port is watched, not only LiveView. The control port therefore
prints `serving 1 client.` and `serving 0 clients.` around each capture press. A
client that attaches and leaves within one 0.1 s poll may go unreported.

A client attached behind a departed one used to be starved until the next send,
and on the `HSCube` port the next cube went to the closed connection. The
activation table's "producer sending nothing" row records that behaviour before
the close check. The check reads the close, so it needs the close to arrive: a
peer that vanishes without a FIN or a reset, which loopback does not produce, is
still noticed only when a send fails. A message queued in the moment between the
close and the release is kept for the next client if the handler has not yet
reached its send, and can still be written to the closed connection if it has.

The release goes through pyigtl's own error path, so every close prints a pyigtl
traceback ending `Error while receiving data: The client closed the connection.`
to standard error. A failed send already printed one; the README and the
quickstart say it is the normal path.

The five new tests use the production grace period and real sockets. Measured,
they take 21 s, and the simulator suite goes from 6.7 s to 27.3 s.

## Documentation impact

- `docs/development/pipeline_test_quickstart.md`: the troubleshooting row for
  empty panes under a connected panel names the producer's warning line.
- `tools/simulators/README.md`: the one-client note names the warning and the
  withdrawal line.

## Completion evidence

Implementation evidence was collected on 2026-09-14 on
`feature/SLIA-018-second-client-receives-nothing`, branched from `main` at
`5e909e9`, Windows 11, `pyigtl` 0.3.4. Final validation was rerun on
2026-09-15, and the project owner completed the manual verification after
those checks.

### Baseline before any change

- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: `Ran 134 tests
  in 6.704s`, `OK`, exit 0.

### New tests against the unchanged `igtl_transport.py`

From `tools\simulators`:
`..\..\.venv\Scripts\python.exe -m unittest tests.test_igtl_transport.ClientWatchTest -v`
reported `Ran 5 tests in 86.266s`, `FAILED (failures=5)`, exit 1:

| Test | Observed failure |
| --- | --- |
| `test_theServedCountIsReportedWhenTheClientGoes` | `AssertionError: False is not true : No attach line was printed:` |
| `test_aSecondAttachedClientIsWarnedAbout` | `AssertionError: False is not true : No warning was printed for a second client:` |
| `test_aSingleClientDrawsNoWarning` | `AssertionError: False is not true : The watch never reported the client, so its silence proves nothing:` |
| `test_aClientReplacingOneThatLeftDrawsNoWarning` | `AssertionError: False is not true : The watch never reported the first client, so its silence proves nothing:` |
| `test_theWarningIsWithdrawnWhenTheWaitingClientLeaves` | `AssertionError: False is not true : No warning was printed for a second client:` |

### New tests against the implementation

Same command: `Ran 5 tests in 21.209s`, `OK`, exit 0.

### Guard tests against mutations

Applied with `unittest.mock.patch` from a runner in the session scratchpad, which
is not part of the change; no source file was edited to produce them.

- No TCP-table confirmation (`establishedServerConnectionCount` always returns
  2): `Ran 2 tests in 22.761s`, `FAILED (failures=2)`, exit 1.
  - `test_aClientReplacingOneThatLeftDrawsNoWarning`: `AssertionError: 'WARNING:'
    unexpectedly found in '127.0.0.1:53954: serving 1 client.\nWARNING:
    127.0.0.1:53954 has 2 clients attached, and a producer serves one client at a
    time. ...'`
  - `test_theWarningIsWithdrawnWhenTheWaitingClientLeaves`: `AssertionError: False
    is not true : The warning was not withdrawn after the waiting client left:`
- Both guards broken (`hasQueuedConnection` always `True`, table count plus one):
  `Ran 1 test in 5.279s`, `FAILED (failures=1)`, exit 1.
  - `test_aSingleClientDrawsNoWarning`: `AssertionError: 'WARNING:' unexpectedly
    found in '127.0.0.1:53962: serving 1 client.\nWARNING: 127.0.0.1:53962 has 2
    clients attached, and a producer serves one client at a time. ...'`

### Required checks after the change

- Simulator suite, `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`:
  `Ran 139 tests in 27.269s`, `OK`, exit 0. No existing test was modified.
- Static analysis, `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21,
  `extensions/SLIAFlow/SLIAFlow` 6 files and `tools/simulators` 32 files, `All
  checks passed!` on both, exit 0.
- Slicer tests, `.\scripts\development\run-slicer-tests.ps1`: module loaded from
  `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`, `Ran 50 tests in
  1.377s`, `OK (skipped=6)`, exit 0. No extension file is changed by this card.
- `git diff --check`: exit 0. Every changed path is in `Files allowed`.

### Agent rehearsal of the manual steps

Not a manual verification: nobody watched a console, so the `Result` column
stays empty. Drivers in the session scratchpad started the launcher
unattended as `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer -RunSeconds 75`,
ran `liveview_client.py --frames 100000` as separate processes, and saved the
launcher's console output to a file.

- Steps 1 to 4 and 7 behaved as the table expects. The second client printed
  only `Connecting to 127.0.0.1:18944 ...` and later `ERROR: no LiveView message
  arrived before the timeout.` The console showed `[acq] 127.0.0.1:18944:
  serving 1 client.`, exactly one `[acq] WARNING: 127.0.0.1:18944 has 2 clients
  attached ...` line and then `[acq] 127.0.0.1:18944: only one client is
  attached again; the warning above no longer applies.` The session ended with
  exit 0 and `No socket was left held.` Timing was not measured to the second,
  because the launcher's tagged lines carry no timestamps.
- Step 5 ended the first client with `Stop-Process -Force` instead of Ctrl-C. The
  console showed `serving 0 clients.`, then `serving 1 client.` when the client
  started again, and no warning. A graceful close is covered by
  `test_theServedCountIsReportedWhenTheClientGoes`.
- Capture path, `-RunSeconds 170`: the launcher's `c` command,
  `python -m stratum_sim capture --port 18950 --no-wait --timeout 15`, was sent five
  times. Three were answered `CAPTURING` and two, sent during a capture already
  in progress, `IGNORED`. The first `READY` started `uc1-genuine`. No `WARNING:`
  line appeared on any port. The genuine runner reads the case folder itself and
  never attaches to 18947, so the HSCube port had no client in this run.
- Load: the simulator suite ran alongside three concurrent runs of
  `ClientWatchTest`. The suite reported `Ran 139 tests in 27.129s`, `OK`; each
  watch run reported `Ran 5 tests` in 21.2 to 21.3 s, `OK`; all four exited 0.

### Releasing a client that closes (implementation step 7)

Commands run from `tools\simulators` unless a full path is given.

- Scratch reproduction, before the change: a served `pyigtl.OpenIGTLinkClient`
  closed, a replacement attached, nothing was sent for 3 s, then one image. The
  server still reported itself connected at 3.12 s, `sendImage` returned `True`,
  and the replacement had received nothing 5 s later. After the change the same
  script printed `replacement received the cube: True` 0.05 s after the send.
- `..\..\.venv\Scripts\python.exe -m unittest tests.test_igtl_transport.ClientWatchTest.test_aClientReplacingOneThatLeftReceivesTheNextMessage`
  against the transport before the change: `Ran 1 test in 30.437s`,
  `FAILED (failures=1)`, exit 1, `AssertionError: False is not true : The
  departed client was not let go while nothing was sent:`.
- `ClientWatchTest` after the change: `Ran 6 tests in 21.716s`, `OK`, exit 0.
- Mutations, from a scratch runner with `unittest.mock.patch`:
  - pyigtl's own read restored on the subclass: the new test, `Ran 1 test in
    30.452s`, `FAILED (failures=1)`, exit 1, with the same assertion as above.
  - `establishedServerConnectionCount` always 2: `Ran 2 tests in 22.861s`,
    `FAILED (failures=1)`, exit 1.
    `test_theWarningIsWithdrawnWhenTheWaitingClientLeaves` failed with
    `The warning was not withdrawn after the waiting client left:`, and
    `test_aClientReplacingOneThatLeftDrawsNoWarning` passed, as the test plan
    now says it does.
- Agent rehearsal on the real acquisition stand-in, not a manual verification:
  `run-end-to-end-session.ps1 -Case 004-02 -NoSlicer -RunSeconds 90`. A scratch
  `HSCube` client attached to 18947 and closed after 3 s; a second attached 1 s
  later; 4 s after that the launcher's `c` command was sent once. The console
  showed `[acq] 127.0.0.1:18947: serving 1 client.`, `serving 0 clients.`,
  `serving 1 client.`, then `Capture 1 complete: READY` and `HSCube for capture 1
  queued on 127.0.0.1:18947: shape (93, 389, 345), uint16.` The second client
  printed `received HSCube: image (93, 389, 345) uint16` with all five
  `SLIAFlow.*` metadata keys and exited 0. No `WARNING:` line appeared; the
  session exited 0 with `No socket was left held.`

The `Required checks after the change` above predate this step. Rerun after it,
on the final source:

- Simulator suite, `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`:
  `Ran 140 tests in 28.047s`, `OK`, exit 0. No test that predates this card was
  modified; among this card's own tests, one comment in
  `test_aClientReplacingOneThatLeftDrawsNoWarning` was corrected.
- Static analysis, `.\scripts\development\run-python-quality.ps1`: Ruff 0.15.21,
  6 and 32 files, `All checks passed!` on both, exit 0.
- Slicer tests: not rerun; no extension file is changed by this step.

### Not run

- `run-slicer-tests.ps1 -Headful` and `-Target Build`: no extension file changed,
  so neither would exercise this card's change.

## Review findings

No findings. The implementation, automated checks, and project-owner manual
verification all match the acceptance criteria.

## Human approval

Activated on 2026-09-14 under the project owner's `Start the next task`
instruction. The owner chose the TCP-table confirmation described under "What
activation measured" the same day, in answer to the finding that the card's
original source for the count cannot see the second client.

On 2026-09-14 the project owner directed that the starvation of a client queued
behind a departed one, first recorded here as a follow-up, be fixed within this
card rather than a new task. That added the close-check requirement, acceptance
criterion 9 and implementation step 7. The `Files allowed` list did not change.

Human approval, manual verification, review, and completion were recorded by
the project owner.
