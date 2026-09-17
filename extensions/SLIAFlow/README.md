# SLIAFlow

SLIAFlow is the 3D Slicer visualization component of the STRATUM demonstrator.
This repository currently provides a minimal scripted-module scaffold and no
diagnostic image generation or clinical decision support.

SLIAFlow is prototype software. It is not clinically validated and must not be
used with private or identifiable patient data.

See the repository-level `README_SLIAFlow_Build.md` for the supported local
Windows build, test, and launch procedure.

## Links connect only when producers are running

Every SLIAFlow link is an OpenIGTLink client. Connect links reaches a port
only when something is listening on it, so start the producers first:

```powershell
scripts\development\run-end-to-end-session.ps1 -Case <case> -NoSlicer
```

The acquisition stand-in serves LiveView (18944), HS Cube (18947) and Control
(18950) as soon as the session starts. The UC1 runner listens on 18945 only
after the first capture reports READY. No UC2 producer exists yet (`SLIA-021`),
so the UC2 link (18946) stays `connecting`. A link still `connecting` after a
few seconds is explained under Status.

The acquisition stand-in opens camera index 0 for LiveView. Stop SLIAFlow's
Laptop Camera, or choose the network stream, before starting the session;
otherwise the stand-in cannot open the camera, exits, and none of its ports
listen.
