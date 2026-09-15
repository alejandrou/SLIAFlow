---
id: SLIA-017
title: Refuse to start a producer on a port another producer already holds
status: active
branch: feature/SLIA-017-producers-share-a-port-silently
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

`pyigtl.OpenIGTLinkServer.__init__` sets
`SocketServer.TCPServer.allow_reuse_address = True` before it binds, which sets
`SO_REUSEADDR`. On Linux that only relaxes `TIME_WAIT`. On Windows it does
something else entirely: it lets a second socket bind an address another socket
is actively listening on, and incoming connections go to one of them by rules
the application does not control. So a producer started on an occupied port
neither fails nor takes over. It joins.

That matters here more than it would in most projects, because the whole
hardware-free architecture rests on one property: stopping one producer and
starting another on the same port changes what SLIAFlow displays. An operator
following the SLIA-014 procedure who does not notice that the first producer is
still alive can watch a swap appear to fail, or worse appear to succeed while
the data still comes from the old producer. The banner would then be the only
thing telling the truth, and only because it travels with the data.

This is a stand-in and tooling defect, not a SLIAFlow defect. SLIAFlow behaved
correctly throughout: its display followed the data on the connection it had.

### What the WP5 demonstrator changes about this

`docs/architecture/WP5_MS5_DEMO_PLAN.md` takes the rig from two ports to seven:
18944 `LiveView`, 18945 `UC1_MV_CLASS` and `UC1_RGB`, 18946 `UC2_BV`, 18947
`HSCube`, 18950 `Control`, with 18948 and 18949 reserved and deliberately unbound.
Every one of them is a fixed port bound by a producer entry point, so the failure
mode this card describes becomes roughly three times more likely to be met per
session, and one of the seven - 18945, which now carries two device names from one
producer - is the port where a silent second listener would be hardest to spot.

Two consequences for this card's scope. The check covers every producer entry
point, including the ones `SLIA-021` adds. And **a producer must never bind a
reserved port**: 18948 and 18949 carry a promise that nothing is listening, and a
black panel that is black because a stray producer took the port is
indistinguishable from one that is black for the right reason.

### What activation measured

Measured on 2026-09-15 on Windows 11 with the installed `pyigtl` 0.3.4, from
scratch probes in the session scratchpad that are not part of the change.

| # | Situation | Observed |
| --- | --- | --- |
| A | Second `igtl_transport.ImageStreamServer` started on a port the first is serving | Starts with no error. Both sockets listen. The defect reproduces. |
| B | Plain bind, no `SO_REUSEADDR`, while a producer listens | Refused, `WinError 10048` |
| C | `pyigtl.OpenIGTLinkServer` subclass with `allow_reuse_address = False`, while a producer listens | Refused, `WinError 10048` |
| D | Same subclass over a listener owned by another process | Refused, `WinError 10048` |
| E | `ImageStreamServer` over a plain listener that did not set `SO_REUSEADDR` | Raises `PermissionError` `WinError 10013`, a message that names neither the port nor the remedy |
| F | Producer that had served a client is stopped; only a `TIME_WAIT` row owned by PID 0 remains | A plain bind succeeds, and so does a restart on the same port |
| G | `SO_REUSEADDR` server started over a producer that did not set it | Refused, `WinError 10013` |
| H | Owner of the listening row | `GetExtendedTcpTable` (`MIB_TCP_STATE_LISTEN`) returns the holding PID; `QueryFullProcessImageNameW` returns its executable path |

Three decisions follow, and none of them widens the card:

1. **The bind is the lock, so the race the card feared is gone.** Rows B, C and D
   show that a server which does not set `SO_REUSEADDR` is refused by Windows
   itself. Clearing `allow_reuse_address` on the transport's own server subclass,
   which `SLIA-018` already introduced, makes the refusal atomic: there is no
   moment between a check and a bind for another producer to use. Row F shows it
   costs nothing on restart, because `SO_REUSEADDR` was never needed to rebind
   over `TIME_WAIT` on Windows. `pyigtl` itself is not changed.
2. **An early check is still worth having, for the operator.** The genuine UC1
   runner classifies before it opens its server, and the acquisition stand-in
   opens the camera first. A refusal that arrives after a GPU run, or after the
   camera has been taken from SLIAFlow, is correct and unhelpful. So each entry
   point also checks its ports before doing any work. That check is advisory -
   the bind stays authoritative - and the message does not claim otherwise.
3. **Sharing has to be wanted on both sides.** Row G shows that the override
   cannot join a producer that did not opt in. That is the right shape rather
   than a limitation: two producers share a port only when both were started with
   `--allow-shared-port`, so a shared port can never be the accident this card is
   about.

## Requirements

- Every producer entry point refuses to serve a port that another socket is
  already listening on, and exits non-zero with an error naming
  `127.0.0.1:<port>` and, where it can be determined, the PID and executable of
  the process holding it.
- The refusal is enforced by the bind: the transport's server does not set
  `SO_REUSEADDR` unless sharing was asked for. Each entry point also checks its
  ports before its first expensive step - dataset load, UC1 classification,
  camera open - so the operator is not kept waiting for a refusal.
- The entry points are the acquisition stand-in (`LiveView`, `HSCube`, `Control`),
  the UC1 arithmetic stand-in and the genuine UC1 runner. A later producer is
  covered by building its server on `igtl_transport.ImageStreamServer`, and a test
  fails if any module in `stratum_sim` constructs a pyigtl server itself.
- A port held by a listener of any kind - not only another producer - is refused
  with the same message, rather than surfacing `WinError 10013`.
- No producer binds a reserved port. Asked to serve 18948 or 18949, a producer
  refuses by the channel's name from `contract.RESERVED_PORTS`, without binding,
  and the override does not change that.
- The error says what to do: stop the other producer, or pass a different port.
  It names `--allow-shared-port` as the only way two producers share a port.
- `--allow-shared-port` is off by default on `acquisition`, `uc1` and `uc1-real`.
  Two producers share a port only when both were started with it.
- A producer that restarts its server on its own port - the existing
  send-failure restart, or a new run right after the last one - is not refused
  because of `TIME_WAIT` connections left by its previous clients.
- The early check obeys the override's rule rather than skipping it: with
  `--allow-shared-port` it still refuses, before any expensive step, a port whose
  holder did not opt in, and says that the holder was not started with the
  switch.
- `acquisition` refuses, before the camera opens and whatever the switches, a port
  configured for two of its own channels.
- A producer that serves a port with the override prints a `WARNING:` naming the
  other producers it shares with, or, when it is alone, that a later join would be
  silent.
- A send-failure restart that cannot bind again stops the producer with a message
  saying so, followed by the refusal, and every refusal on Windows ends with the
  `Stop-Process -Id` command for the holder.

## Out of scope

- Changing `pyigtl`, or vendoring a patched copy of it. Setting a class attribute
  on `igtl_transport`'s existing subclass is not a change to pyigtl.
- Any change to SLIAFlow.
- Port allocation policy. The seven ports stay what
  `docs/architecture/SLIAFLOW_IMPLEMENTATION_ROADMAP.md` says they are.
- The session launcher. Its free-port preflight and `-StopStrays` stay as they
  are, and it already reports a producer that exits non-zero.
- `capture_client.py`, which is a client and binds nothing.
- Retiring the arithmetic stand-in, which is `SLIA-025`. It is covered here
  because it is still an entry point today.

## Files allowed

- `tools/simulators/stratum_sim/igtl_transport.py`
- `tools/simulators/stratum_sim/acquisition_sim.py`
- `tools/simulators/stratum_sim/uc1_sim.py`
- `tools/simulators/stratum_sim/uc1_runner.py`
- `tools/simulators/tests/test_igtl_transport.py`
- `tools/simulators/tests/test_acquisition_sim.py`
- `tools/simulators/tests/test_uc1_sim.py`
- `tools/simulators/tests/test_uc1_runner.py`
- `tools/simulators/README.md`
- `docs/development/end_to_end_verification.md`
- `tasks/{backlog,active,review,completed}/SLIA-017-producers-share-a-port-silently.md`

## Relevant skills and references

- `docs/development/end_to_end_verification.md`, the prerequisites table and its
  free-port check, and failures table row 2
- `pyigtl/comm.py` `OpenIGTLinkServer.__init__` in the installed 0.3.4, which
  assigns `allow_reuse_address` on `socketserver.TCPServer` before binding
- `tools/simulators/stratum_sim/igtl_transport.py` `_DepartureAwareServer` and
  `establishedServerConnectionCount`, the precedent from `SLIA-018`
- Windows `SO_REUSEADDR` and `SO_EXCLUSIVEADDRUSE` semantics, as measured above
- `scripts/development/run-end-to-end-session.ps1` `Assert-PortAvailable`, the
  launcher's own check this card complements

## Approved dependencies

None. `socket`, `ctypes` and `functools` are standard library.

## Reproduction

1. Start any producer on 18945 and leave it running.
2. Start a second producer on 18945.
3. `netstat -ano | findstr 18945`.

Observed: both processes appear as `LISTENING` on the same address, and the
second producer prints its ordinary startup banner as though it owned the port.
Expected: the second producer exits with an error.

## Implementation plan

1. Record the baseline: simulator suite and Ruff on the unchanged tree.
2. Write the tests below and run each against the unchanged code; record each
   failure.
3. In `igtl_transport.py`:
   - add `PortRefusedError(OSError)`;
   - add `listeningProcessIds(port)` from the TCP table and
     `processImageName(pid)`, each returning `None` or empty where the answer
     cannot be read;
   - add `assertPortCanBeServed(port, allowSharedPort=False)`: refuse a reserved
     port by name, otherwise try a bind without `SO_REUSEADDR` and refuse if it
     fails, skipping only the bind when sharing was asked for;
   - set `allow_reuse_address = False` on `_DepartureAwareServer`, and add a
     sharing subclass that sets it back to `True`;
   - give `ImageStreamServer` an `allowSharedPort=False` argument, refuse a
     reserved port before binding, and turn a bind refusal (`WinError 10048` or
     `10013`, or `EADDRINUSE` / `EACCES` elsewhere) into `PortRefusedError`
     with the same message.
4. In `uc1_sim.py` and `uc1_runner.py`: add `--allow-shared-port`, call
   `assertPortCanBeServed` before the dataset is loaded, and pass the flag
   through `streamMaps` to the server. Their existing `OSError` handling already
   prints `ERROR:` and exits 1.
5. In `acquisition_sim.py`: add `--allow-shared-port` as a command-line-only
   switch, check every port the chosen scene opens before the dataset step and
   the camera, give `streamLiveView` the same `serverFactory` parameter
   `serveRecordedCapture` already has, and turn `PortRefusedError` from either
   into `ERROR:` and exit 1.
6. Run the new tests again, then run each guard against the mutations named in
   the test plan, applied with `unittest.mock.patch` from a scratch runner so no
   source file is edited to produce them.
7. Update the README and the end-to-end verification prerequisites.
8. Run the full simulator suite, Ruff on both targets, and the Slicer suite.

## Acceptance criteria

1. An `ImageStreamServer` started on a port another producer is serving raises
   `PortRefusedError` naming `127.0.0.1:<port>`, telling the operator to stop the
   other producer or pass a different port, and naming `--allow-shared-port`.
2. Where the holder can be determined, the error names its PID and executable.
3. A port held by a listener that is not a producer is refused with the same
   error, not with `WinError 10013`.
4. A reserved port is refused by its channel name, with or without the override,
   and is never bound.
5. Two producers both started with the override share a port; a producer started
   with the override does not join one started without it.
6. A producer restarts on its own port after serving a client, with no refusal.
7. `uc1`, `uc1-real` and `acquisition` each exit 1 before doing their work when a
   port they need is served, printing the port in an `ERROR:` line.
8. `--allow-shared-port` on each of the three entry points reaches the server,
   and is off by default.
9. No module in `stratum_sim` other than `igtl_transport` constructs a pyigtl
   server, so a later producer inherits the refusal.
10. The existing simulator suite and Ruff pass with no existing test modified.
11. The README and the end-to-end verification prerequisites describe the
    refusal and the override.
12. On a real rig, a second producer on an occupied port exits with the message,
    and `netstat` shows one listener.
13. With `--allow-shared-port`, a port held by a producer that did not opt in is
    refused by the early check, saying the holder was not started with the switch,
    and `uc1`, `uc1-real` and `acquisition` each exit 1 before their work.
14. `acquisition` exits 1 before the camera opens when one port is configured for
    two of its channels, with or without the override.
15. Between two separate processes, both opted in share the port and the joiner's
    `WARNING:` names the other's PID; a separate producer that did not opt in is
    refused by name, with its `Stop-Process -Id` command.
16. A send-failure restart that finds its port taken stops with an error saying the
    restart could not bind.

## Test plan

| Acceptance criterion | Verified by | Type |
| --- | --- | --- |
| 1. Occupied port refused, with remedy and override named | `PortRefusalTest.test_aSecondServerOnAnOccupiedPortIsRefused` | automated |
| 2. Holder named | `PortRefusalTest.test_theRefusalNamesTheProcessHoldingThePort` | automated |
| 3. Any listener refused in the same words | `PortRefusalTest.test_aPortHeldByAnyListenerIsRefusedTheSameWay` | automated |
| 4. Reserved port refused by name, never bound | `PortRefusalTest.test_aReservedPortIsRefusedByNameWithoutBinding`; manual step 3 | automated, manual |
| 5. Sharing needs both sides | `PortRefusalTest.test_twoProducersThatBothOptInShareAPort`, `PortRefusalTest.test_theOverrideDoesNotJoinAProducerThatDidNotOptIn`; manual step 4 | automated, manual |
| 6. Restart on own port not refused | `PortRefusalTest.test_aProducerRestartsOnItsOwnPortAfterServingAClient`; manual step 6 | automated, manual |
| 7. Entry points exit 1 before their work | `Uc1SimPortTest.test_anOccupiedPortExitsBeforeTheDatasetIsRead`, `Uc1RunnerPortTest.test_anOccupiedPortExitsBeforeTheDatasetIsRead`, `AcquisitionPortTest.test_anOccupiedPortExitsBeforeTheCameraOpens` | automated |
| 8. Override flag reaches the server, off by default | `Uc1SimPortTest.test_allowSharedPortReachesTheServer`, `Uc1RunnerPortTest.test_allowSharedPortReachesTheServer`, `AcquisitionPortTest.test_allowSharedPortReachesTheServers` | automated |
| 9. Only the transport builds a server | `PortRefusalTest.test_onlyTheTransportConstructsAPyigtlServer` | automated |
| 10. Existing suite and Ruff unchanged | `tools\simulators\tests\run_tests.py`, `run-python-quality.ps1` | automated |
| 11. Documentation describes it | Manual step 7 | manual |
| 12. Refusal on a real rig | Manual steps 1, 2 and 5 | manual |
| 13. Override's early check refuses a non-opted-in holder | `PortRefusalTest.test_theEarlyCheckWithTheOverrideRefusesAProducerThatDidNotOptIn`, `PortRefusalTest.test_theEarlyCheckWithTheOverrideAcceptsAProducerThatOptedIn`, the `--allow-shared-port` subtests of the three `test_anOccupiedPortExitsBefore...` tests; manual step 4 | automated, manual |
| 14. Repeated acquisition port refused | `AcquisitionPortTest.test_aPortConfiguredForTwoChannelsExitsBeforeTheCameraOpens` | automated |
| 15. Sharing between separate processes | `SeparateProcessSharingTest.test_producersInSeparateProcessesShareWhenBothOptIn`, `SeparateProcessSharingTest.test_aSeparateProducerThatDidNotOptInIsNotJoined`; manual step 8 | automated, manual |
| 16. Failed restart says why | `PortRefusalTest.test_aRestartThatFindsItsPortTakenSaysWhy` | automated |

Tests to add or change, and how each one will be shown to fail first:

- The `PortRefusalTest` tests start real servers on free local ports and read
  the raised error, because the error text is what reaches the operator.
- `test_aSecondServerOnAnOccupiedPortIsRefused` and
  `test_theRefusalNamesTheProcessHoldingThePort` fail against the unchanged
  transport because the second server starts: no `OSError` is raised.
- `test_aPortHeldByAnyListenerIsRefusedTheSameWay` fails against the unchanged
  transport because the error raised is `WinError 10013`, whose text names
  neither the port nor the remedy.
- `test_aReservedPortIsRefusedByNameWithoutBinding` fails against the unchanged
  transport because the server is constructed and nothing is raised. The pyigtl
  server class is patched so that no real socket touches 18948 or 18949.
- `test_twoProducersThatBothOptInShareAPort` and
  `test_theOverrideDoesNotJoinAProducerThatDidNotOptIn` fail against the
  unchanged transport with `TypeError`, because `allowSharedPort` does not exist.
  That red is weak, so the second is also shown failing against a mutation that
  sets `SO_REUSEADDR` on every server regardless of the flag.
- `test_aProducerRestartsOnItsOwnPortAfterServingAClient` passes against the
  unchanged transport, because the risk it guards is one this change could
  introduce. It is shown failing against a mutation whose check treats any TCP
  row on the port, including `TIME_WAIT`, as a holder.
- `test_onlyTheTransportConstructsAPyigtlServer` holds today. It is shown failing
  by pointing its scan at a scratch copy of the package with one extra module
  that constructs `pyigtl.OpenIGTLinkServer`.
- The three `test_anOccupiedPortExitsBefore...` tests hold a real port, run the
  entry point's `main` on it, and fail if that entry point touches its dataset
  or camera. Against the unchanged code they fail because the `ERROR:` line
  names the missing dataset or case rather than the port, and for the stand-ins
  whose dataset step is patched to succeed, because `main` returns 0 after
  binding alongside the holder. The interrupt flag is patched to ask for a stop
  so a red run cannot hang.
- The three `test_allowSharedPort...` tests fail against the unchanged code
  because argparse rejects `--allow-shared-port` with exit status 2.
- The two tests that name the holder read the Windows TCP table and skip with a
  stated reason off Windows. This project runs on Windows 11, so a skip there is
  a failure to investigate.
- No existing test is modified. Existing tests that patch `ImageStreamServer`
  with a `return_value` mock accept the new keyword argument unchanged.

## Manual verification

Run in PowerShell from the repository root, with the repository `.venv`, the
staged UC1 build, and recorded case `004-02` under `input\bin\bin`. Slicer is not
needed. In every step, a producer's own startup banner such as `Real UC1 server
listening on ...` appearing in shell 2 is the failure this card prevents.

| # | Action | Expected observation | Result |
| --- | --- | --- | --- |
| 1 | Shell 1: `.\scripts\development\run-end-to-end-session.ps1 -Case 004-02 -NoSlicer`. Wait until LiveView, HSCube and Control are listening. Shell 2: `$env:PYTHONPATH = "$PWD\tools\simulators"` then `.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02 --port 18947` | Shell 2 prints, within a second and before any `[uc1]` pipeline output, one `ERROR:` line naming `127.0.0.1:18947`, the PID and `python.exe` of the acquisition stand-in, and telling you to stop the other producer or pass a different port. It exits; `$LASTEXITCODE` is 1. | |
| 2 | Shell 2: `netstat -ano \| findstr 18947` | Exactly one `LISTENING` row on `127.0.0.1:18947`, whose PID is the one the error named. | |
| 3 | Shell 2: the step 1 command with `--port 18948`, then again with `--port 18948 --allow-shared-port`, then `netstat -ano \| findstr 18948` | Both runs print an `ERROR:` line saying 18948 is reserved for `Stereoscopic` and exit 1. `netstat` prints nothing for 18948. | |
| 4 | Shell 2: the step 1 command with `--allow-shared-port` | Refused within a second, before any `[uc1]` pipeline output, with an `ERROR:` line naming 18947 and the stand-in's PID, saying it was not started with `--allow-shared-port`, and ending `To stop it: Stop-Process -Id <PID>`. `$LASTEXITCODE` is 1. | |
| 5 | Shell 1: press `c` and wait for `uc1-genuine` to report `Real UC1 server listening on 127.0.0.1:18945`. Shell 2: the step 1 command with `--port 18945`. | Shell 2 is refused naming 18945 and the genuine runner's PID, before running the pipeline. Shell 1 keeps serving; `netstat -ano \| findstr 18945` shows one `LISTENING` row. This is the SLIA-014 swap with the first producer deliberately left running. | |
| 6 | Shell 1: press `q`. Shell 2: `.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02 --cycles 2`, and as soon as it exits run the same command again | Both runs print `Real UC1 server listening on 127.0.0.1:18945` with no `ERROR:` line; the second is not refused by the first run's leftover connections. Stop each with Ctrl-C if no client connects. | |
| 7 | Read the "A port that is already served" section of `tools\simulators\README.md` and the ports row of the prerequisites table in `docs\development\end_to_end_verification.md` | Both say that a producer refuses an occupied or reserved port, what to do about it, and that `--allow-shared-port` must be given to both producers. | |
| 8 | Two shells, each with `$env:PYTHONPATH` set as in step 1. Shell 1: `.\.venv\Scripts\python.exe -m stratum_sim uc1-real input\bin\bin\004-02 --port 18955 --allow-shared-port`. Once it is listening, shell 2: the same command. Then `netstat -ano \| findstr 18955`, and Ctrl-C in both. | Shell 1 prints `WARNING: 127.0.0.1:18955 is served with --allow-shared-port ...`. Shell 2 runs the pipeline and prints `WARNING: 127.0.0.1:18955 is shared with PID <shell 1's PID> (python.exe) ...`. `netstat` shows two `LISTENING` rows on 18955 with different PIDs. | |

## Risks

The early check is a probe and can be overtaken: another producer can take the
port between the check and the bind. That is why the bind itself is the
authority and the check is only there to fail fast. The message does not
promise more than that.

The holder's PID is read after the bind has already been refused, so a holder
that exits in that instant is reported as unidentified rather than wrongly
named. Off Windows no holder is named at all.

`SO_REUSEADDR` also governs rebinding over `TIME_WAIT`. Measured on Windows it is
not needed for that, which is row F above. Off Windows it is, so a producer
restarted within a minute of serving a client could be refused there. This
project runs on Windows 11; the risk is recorded rather than engineered around.

The send-failure restart inside `ImageStreamServer` now binds without
`SO_REUSEADDR` too. If another producer takes the port during the one-second
restart gap, the running producer stops with the refusal instead of joining. That
is this card's rule applied mid-run, and it is loud rather than silent: the error
says the restart could not bind. Retrying the bind was rejected, because a
producer that waits for a port to come back would hide exactly the stray this
card exists to expose.

A producer that was first on a shared port is not told when another joins it. Its
startup warning says a later join would be silent, and the joiner names it. A
live notice would have to poll the TCP table for other listeners and is left out.

Repeated acquisition ports are refused in `acquisition_sim.main`, because
`config.py` is outside `Files allowed`. Validating them in
`config.loadSimulatorConfig` would also cover `--dataset-only` and any later
caller; that is a candidate follow-up, not required for this card.

A third-party listener that opened the port with `SO_EXCLUSIVEADDRUSE` or without
`SO_REUSEADDR` was already refused before this change, with `WinError 10013`. The
change is to the words, not to the outcome.

## Documentation impact

- `docs/development/end_to_end_verification.md`: the prerequisites free-port
  check becomes advisory once the producers enforce it themselves, and the
  finding that motivated this card is already recorded there.
- `tools/simulators/README.md`: the refusal, the reserved-port refusal, and the
  override that has to be given on both sides.

## Completion evidence

Collected on 2026-09-15 on `feature/SLIA-017-producers-share-a-port-silently`,
branched from `main` at `0531271`, Windows 11, `pyigtl` 0.3.4, Ruff 0.15.21.
Nothing is committed.

### Baseline before any change

- `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`: `Ran 140 tests
  in 27.675s`, `OK`, exit 0.
- `.\scripts\development\run-python-quality.ps1`: 6 and 32 files, `All checks
  passed!` on both, exit 0.

### New tests against the unchanged code

From `tools\simulators`:
`..\..\.venv\Scripts\python.exe -m unittest tests.test_igtl_transport.PortRefusalTest tests.test_uc1_sim.Uc1SimPortTest tests.test_uc1_runner.Uc1RunnerPortTest tests.test_acquisition_sim.AcquisitionPortTest -v`
reported `Ran 14 tests in 4.832s`, `FAILED (failures=9, errors=9)` counted by
subtest, exit 1.

| Test | Observed |
| --- | --- |
| `test_aSecondServerOnAnOccupiedPortIsRefused` | `AssertionError: OSError not raised` |
| `test_theRefusalNamesTheProcessHoldingThePort` | `AssertionError: OSError not raised` |
| `test_aPortHeldByAnyListenerIsRefusedTheSameWay` | `AssertionError: '127.0.0.1:51209' not found in '[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions'` |
| `test_aReservedPortIsRefusedByNameWithoutBinding` | `AssertionError: OSError not raised` for 18948 and 18949; `TypeError: ... unexpected keyword argument 'allowSharedPort'` for the override subtests; `AttributeError: ... no attribute 'assertPortCanBeServed'` for the early-check subtests |
| `test_twoProducersThatBothOptInShareAPort` | `TypeError: ImageStreamServer.__init__() got an unexpected keyword argument 'allowSharedPort'` |
| `test_theOverrideDoesNotJoinAProducerThatDidNotOptIn` | Same `TypeError`; see the mutations below for its meaningful red |
| `test_aProducerRestartsOnItsOwnPortAfterServingAClient` | Passed, as planned; see mutation M2 |
| `test_onlyTheTransportConstructsAPyigtlServer` | Passed, as planned; see mutation M3 |
| `Uc1SimPortTest.test_anOccupiedPortExitsBeforeTheDatasetIsRead` | `AssertionError: The dataset was read.` |
| `Uc1RunnerPortTest.test_anOccupiedPortExitsBeforeTheDatasetIsRead` | `AssertionError: The dataset was read.` |
| `AcquisitionPortTest.test_anOccupiedPortExitsBeforeTheCameraOpens` | `AssertionError: The case was read.` |
| `Uc1SimPortTest.test_allowSharedPortReachesTheServer` | `SystemExit: 2` for `--allow-shared-port`; the default subtest passed |
| `Uc1RunnerPortTest.test_allowSharedPortReachesTheServer` | `SystemExit: 2` for `--allow-shared-port`; the default subtest passed |
| `AcquisitionPortTest.test_allowSharedPortReachesTheServers` | `SystemExit: 2` for `--allow-shared-port`; the default subtest failed with `Lists differ: [] != [51224, 51225, 51226]`, because `serveRecordedCapture` bound its factory at import time |

Corrections to the test plan, recorded rather than rewritten: the entry-point
tests failed on the patched dataset or case read propagating, not on an `ERROR:`
line naming the dataset; and the two UC1 default-flag subtests pass against the
unchanged code, because "off by default" was already true there, so their red
comes from the `--allow-shared-port` subtest alone.

### New tests against the implementation

Same command: `Ran 14 tests in 2.828s`, `OK`, exit 0. The pyigtl traceback
ending `Error while receiving data: The client closed the connection.` printed
during `test_twoProducersThatBothOptInShareAPort` is the documented release of a
closing client, not a failure.

### Guard tests against mutations

Applied with `unittest.mock.patch` from
`scratchpad\slia017_mutations.py`, which is not part of the change; no source
file was edited to produce them.

- M1, `_DepartureAwareServer.allow_reuse_address` forced to `True`: `Ran 2 tests
  in 2.020s`, `FAILED (failures=2)`, exit 1.
  `test_theOverrideDoesNotJoinAProducerThatDidNotOptIn` and
  `test_aSecondServerOnAnOccupiedPortIsRefused` each `AssertionError: OSError not
  raised`.
- M2, `ImageStreamServer.start` refusing any TCP row on its port, `TIME_WAIT`
  included: `Ran 1 test in 0.183s`, `FAILED (errors=1)`, exit 1.
  `test_aProducerRestartsOnItsOwnPortAfterServingAClient` raised the mutation's
  `PortRefusedError` on the restart.
- M3, the scan pointed at a scratch copy of `stratum_sim` with an added
  `uc2_runner.py` constructing `pyigtl.OpenIGTLinkServer`: `Ran 1 test in
  0.113s`, `FAILED (failures=1)`, exit 1, `AssertionError: Lists differ:
  ['uc2_runner.py'] != []`.

### Required checks after the change

- Simulator suite, `.\.venv\Scripts\python.exe tools\simulators\tests\run_tests.py`:
  `Ran 154 tests in 30.849s`, `OK`, exit 0. No existing test was modified.
- Static analysis, `.\scripts\development\run-python-quality.ps1`: the first run
  reported `B023 Function definition does not bind loop variable constructed` in
  this card's own `test_allowSharedPortReachesTheServers`; after binding it as a
  default argument, 6 and 32 files, `All checks passed!` on both, exit 0.
- Slicer tests, `.\scripts\development\run-slicer-tests.ps1`: module loaded from
  `C:\stratum\extensions\SLIAFlow\SLIAFlow\SLIAFlow.py`, `Ran 50 tests in
  1.306s`, `OK (skipped=6)`, exit 0. No extension file is changed by this card.
- `git diff --check`: exit 0. Every changed path is in `Files allowed`.

### Agent rehearsal with real processes

Not a manual verification: nobody watched a console, so the `Result` column
stays empty. A scratch process served an `ImageStreamServer` on 18953; `netstat`
showed one `LISTENING` row owned by PID 30868. Then:

- `python -m stratum_sim uc1-real input\bin\bin\004-02 --port 18953` exited 1
  after 197 ms, before any pipeline output, printing
  `ERROR: 127.0.0.1:18953 is already being served by PID 30868 (python.exe). ...`
  `netstat` still showed the single listener.
- The same command with `--port 18948` exited 1 printing
  `ERROR: 127.0.0.1:18948 is reserved for Stereoscopic, ...`; `netstat` showed
  nothing on 18948.

The PID named is the interpreter that owns the socket, which is the one `netstat`
shows. Started through the repository `.venv` launcher, that is a child of the
PID `Start-Process` reports, so stopping the producer means stopping the PID the
message names.

### Owner findings before review, and their fixes

Raised by the project owner on 2026-09-15 after the first completion report:

1. High: `--allow-shared-port` skipped the early check, so a producer that did not
   opt in was discovered only at the bind, after `uc1-real`'s GPU run or
   `acquisition`'s case read and camera open. Fixed: the probe sets
   `SO_REUSEADDR` when sharing is asked for. Measured first from
   `scratchpad\port_probe3.py` across two processes: over a plain holder the probe
   is refused `WinError 10013`; over a sharing holder it binds; on a free port it
   binds; and the holder accepted a client after each probe.
2. Medium: `servedPorts` could return one port twice, and each probe passed.
   Fixed: `repeatedServedPortMessage` refuses it before the camera, with or
   without the override.
3. Low: sharing was tested only inside one process. Fixed:
   `SeparateProcessSharingTest` runs the holder in its own interpreter, and
   manual step 8 covers two launched producers.

Also added for diagnosis: the sharing `WARNING:`, the restart context, the
`Stop-Process -Id` line, and "this producer's own process" when the holder is the
producer itself.

New and extended tests against the code before these fixes, from
`tools\simulators`:
`..\..\.venv\Scripts\python.exe -m unittest` with the nine test ids of criteria
13 to 16 and the three extended occupied-port tests: `Ran 9 tests in 3.507s`,
`FAILED (failures=9)` counted by subtest, exit 1.

| Test | Observed |
| --- | --- |
| `test_theEarlyCheckWithTheOverrideRefusesAProducerThatDidNotOptIn` | `AssertionError: PortRefusedError not raised` |
| `test_theEarlyCheckWithTheOverrideAcceptsAProducerThatOptedIn` | Passed, as expected: the old check returned early |
| `test_aRestartThatFindsItsPortTakenSaysWhy` | `AssertionError: 'restarted after a failed send' not found in '127.0.0.1:65214 is already being served by PID 29988 (python.exe). ...'` |
| `SeparateProcessSharingTest.test_aSeparateProducerThatDidNotOptInIsNotJoined` | `AssertionError: PortRefusedError not raised` |
| `SeparateProcessSharingTest.test_producersInSeparateProcessesShareWhenBothOptIn` | `AssertionError: 'WARNING:' not found in ''` |
| The three `test_anOccupiedPortExitsBefore...`, `--allow-shared-port` subtest | `AssertionError: The dataset was read.` twice, `The case was read.` for acquisition |
| `test_aPortConfiguredForTwoChannelsExitsBeforeTheCameraOpens` | `AssertionError: The case was read.` in both subtests |

After the fixes:

- All SLIA-017 port classes (`PortRefusalTest`, `SeparateProcessSharingTest`,
  `Uc1SimPortTest`, `Uc1RunnerPortTest`, `AcquisitionPortTest`): `Ran 20 tests in
  6.302s`, `OK`, exit 0.
- Simulator suite: `Ran 160 tests in 36.857s`, `OK`, exit 0.
- `run-python-quality.ps1`: 6 and 32 files, `All checks passed!` on both, exit 0.
- `git diff --check`: exit 0; every changed path is in `Files allowed`.
- The Slicer suite was not rerun: no extension file changed since its run above.

Agent rehearsal with real processes, from `scratchpad\slia017_rehearsal2.py`, not
a manual verification:

- `uc1-real input\bin\bin\004-02 --port 18953 --allow-shared-port` over a
  producer without the override (PID 7632) exited 1 after 187 ms with empty
  stdout, printing `ERROR: 127.0.0.1:18953 is already being served by PID 7632
  (python.exe). This producer was started with --allow-shared-port, but the one
  already serving the port was not started with --allow-shared-port, ... To stop
  it: Stop-Process -Id 7632`.
- Two producers with the override: the first (PID 1236) printed
  `WARNING: 127.0.0.1:18953 is served with --allow-shared-port. ...`; the joiner
  printed `WARNING: 127.0.0.1:18953 is shared with PID 1236 (python.exe), started
  with --allow-shared-port too. ...`.
- Afterwards `netstat` showed no listener left on 18953.

### Not run

- `run-slicer-tests.ps1 -Headful` and `-Target Build`: no extension file changed,
  so neither would exercise this card's change.
- Manual steps 1 to 8: they need the project owner, the laptop camera and a
  person reading the consoles.

## Review findings

Reserved for review.

## Human approval

Activated on 2026-09-15 under the project owner's `Start the next task`
instruction. Selected because it is the eligible backlog task earliest in
architectural order: `SLIA-022`, the highest-priority eligible card, stays
blocked on `ADR-0001`, which is still proposed; `SLIA-025` has open owner
questions; `SLIA-019` is to be superseded by `SLIA-025`; and the WP5 plan names
`SLIA-017` as worth taking before the six-panel layout. `SLIA-009` follows that
layout and `SLIA-015` is independent of the demonstrator order.

Required before review and completion.
