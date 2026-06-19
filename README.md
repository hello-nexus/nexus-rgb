# nexus-rgb

Workspace for [Nexus](https://hellonexus.com)'s **headless OpenRGB fork** - the RGB engine that [`nexus-service`](https://github.com/hello-nexus/nexus-service) embeds as a child process to drive the full upstream catalog of consumer RGB devices without bundling Qt. The public fork lives at [`hello-nexus/openrgb-headless`](https://github.com/hello-nexus/openrgb-headless) (GPLv2); this repo is the workspace that builds it, ships helper scripts (`bundle-macos.sh`, `scripts/`), and documents what we changed against upstream and how to keep merging from it.

The rest of this document is about what was done to produce the headless fork, why each decision was made, and how to keep merging upstream updates without breaking it.

---

## What we built

A **headless fork of OpenRGB** that strips Qt entirely (Widgets, Gui, Core,
DBus) and ships only the SDK server. The motivation was concrete: we wanted to
embed OpenRGB inside `nexus-service` as a child process so the .NET service
could control the user's RGB hardware over loopback TCP, without bundling 12+
MiB of Qt runtime DLLs that the SDK server never actually uses at runtime.

Result:

| Build | Size |
|---|---|
| Upstream OpenRGB Windows portable | ~13 MiB download / ~25 MiB extracted |
| Our headless fork (Windows x64, full bundle with hidapi/libusb/PawnIO DLLs) | **~7.4 MiB** |
| Our headless fork (Linux x64, dynamic) | **~11 MiB** |

The device controllers and the SDK protocol are unchanged from upstream.

The fork lives at:

- **Public**: https://github.com/hello-nexus/openrgb-headless (GPLv2 fork; we're
  obligated to make the source available since we redistribute the binary)
- **Local**: `./openrgb-headless/` (this folder)
- **Bundled into**: `nexus-service/Bundled/win-x64/openrgb/` (binary + DLLs +
  LICENSE, from the fork's CI) and `nexus-service/Bundled/osx-arm64/openrgb/`
  (binary + relinked dylibs + LICENSE, from `bundle-macos.sh`)

---

## Why a fork at all?

OpenRGB is the only realistic source of broad RGB device support, with
controllers covering virtually every consumer RGB product. Writing our own
device drivers would be 7+ years of community work. The integration constraints
ruled out simply linking against an existing C# OpenRGB library:

1. Our service is `<PublishAot>true</PublishAot>` (Native AOT). Every existing
   .NET RGB library (RGB.NET, OpenRGB.NET) uses runtime reflection and isn't
   AOT-safe.
2. OpenRGB itself is GPL-2.0 and we ship as private source. We comply via
   "mere aggregation": we run OpenRGB as a separate process and talk to it via
   loopback TCP. No linking, no ABI coupling.
3. The official OpenRGB Windows portable is 25 MiB extracted. Of that, ~12 MiB
   is Qt5 runtime DLLs that the `--server` code path doesn't actually use.

So the architecture is: **our service launches `OpenRGB-headless --server` as a
child process** and speaks the OpenRGB SDK binary protocol on `127.0.0.1:6742`.
The fork exists purely to make that child process small.

---

## Why upstream compatibility is critical

OpenRGB is **actively developed**. Upstream ships new device support every
month (new mice, new keyboards, new motherboards). If our fork drifts away from
upstream, we lose access to all that work. The fork only makes sense if we can
**continue merging upstream updates** with low overhead.

Every decision in the fork is biased toward "easy to merge upstream." Specifically:

- **We don't touch any controller code**, ever. Everything in `Controllers/`
  is byte-identical to upstream, so upstream changes apply trivially.
- **We don't touch any networking, detection, or resource-management code**.
  `NetworkServer.cpp`, `NetworkProtocol.cpp`, `NetworkClient.cpp`,
  `ResourceManager.cpp`, `SettingsManager.cpp`, `ProfileManager.cpp`,
  `LogManager.cpp` - all byte-identical to upstream.
- **We don't change the qmake build system**. We could have switched to CMake
  for cleaner headless builds, but that would create a permanent merge wall
  with upstream. Instead, we keep `OpenRGB.pro` and edit it minimally.
- **We document every conflict-resolution rule** so the next upstream sync is
  routine, not a research project (see
  [`openrgb-headless/MAINTAINING.md`](openrgb-headless/MAINTAINING.md)).

The cost of a fork is paid every upstream sync. Our cleanup is designed to
keep that cost as low as possible.

---

## What we changed in the fork

### Files physically deleted

These exist only to drive a graphical interface and have no headless purpose:

| Path | What it is |
|---|---|
| `qt/` (entire directory, ~50 files) | All dialogs, pages, widgets, themes, fonts, icons, translations |
| `dependencies/ColorWheel/` | Pure `QWidget` colour-picker, only used by the GUI |
| `SuspendResume/` (entire directory) | Per-platform suspend/resume listeners that depended on `QAbstractNativeEventFilter` (Windows) or `QDBusConnection` (Linux/FreeBSD). The host that embeds the headless server detects OS power events itself. |
| `PluginManager.cpp/h` | The GUI plugin loader (`QPluginLoader` + `QWidget` plugin ABI) |
| `OpenRGBPluginInterface.h` | Qt-bound plugin interface |
| `Documentation/Images/` | GUI screenshots |
| `README-HEADLESS.md` | Superseded by the rewritten `README.md` |

That's 53,000+ lines of GUI code removed. Total non-controller diff vs. upstream.

### Files relocated

| From | To | Reason |
|---|---|---|
| `qt/hsv.cpp` | `hsv.cpp` (top level) | Pure integer RGB↔HSV math, included by several controllers. The only Qt-free file in `qt/`. |
| `qt/hsv.h` | `hsv.h` (top level) | Same. |

### Files edited

| File | What changed |
|---|---|
| `OpenRGB.pro` | Set `QT =` (clears all Qt modules), drop `lrelease`/`embed_translations`/FORMS/RESOURCES/TRANSLATIONS, drop GUI source list builders, drop `qt/` from INCLUDEPATH, add `.` to INCLUDEPATH so the relocated `hsv.h` resolves, drop ColorWheel/PluginManager/SuspendResume references, drop Linux desktop install rules, drop Windows `RC_ICONS`, drop macOS `.app` bundle config. Always defines `OPENRGB_HEADLESS`. |
| `startup/startup.cpp` | Rewritten as a small SDK-server boot loop with no GUI branches. Removed `#include <QApplication>`, removed `#include "OpenRGBDialog.h"`, removed the entire `if(ret_flags & RET_FLAG_START_GUI)` block. Always runs the server. |
| `startup/main_Windows.cpp` | Removed the `#include <QApplication>` line. |
| `startup/main_FreeBSD_Linux_MacOS.cpp` | Removed the `#include "macutils.h"` block (`macutils.h` was deleted with the `qt/` folder). |
| `.github/workflows/headless.yml` | Drops `CONFIG+=headless` from the qmake invocation (headless is the only mode now). |

### CI

`.github/workflows/headless.yml` runs Windows (MSVC + jom) and Linux
(GCC + make) builds on every push and uploads bundled artifacts:

- `OpenRGB-headless.exe` + `hidapi.dll` + `libusb-1.0.dll` + `PawnIOLib.dll` +
  `SmbusI801.bin` + `SmbusPIIX4.bin` + `SmbusNCT6793.bin` + `LpcIO.bin` +
  `LICENSE-OpenRGB.txt` + `README.txt` (Windows). The `*.bin` files are PawnIO
  chipset modules - PawnIOLib loads them at runtime to probe SMBus. Without
  them, RGB DRAM is invisible to OpenRGB. CI fails the Windows job if any
  required module is missing.
- `OpenRGB-headless` + `LICENSE-OpenRGB.txt` + `README.txt` (Linux)

Both are tagged with the upstream source URL for GPL §3 compliance. We download
the Windows artifact and drop it into `nexus-service/Bundled/win-x64/openrgb/`.

There is no macOS CI job. The macOS binary is built locally on Apple Silicon
and packaged by `bundle-macos.sh` (see [Building](#building)).

---

## Building

### Get the fork

`./openrgb-headless/` holds the fork checkout (the `headless` branch of
[`hello-nexus/openrgb-headless`](https://github.com/hello-nexus/openrgb-headless)).
The path is planned to become a git submodule; until that registration
lands, clone it in place:

```bash
git clone --branch headless https://github.com/hello-nexus/openrgb-headless.git openrgb-headless
```

### Build the binary

Per-platform toolchains and qmake invocations live in the fork's own README
([`openrgb-headless/README.md`](https://github.com/hello-nexus/openrgb-headless/blob/headless/README.md), "Building"
section) - that copy is authoritative, so it isn't duplicated here. In
practice:

- **Windows / Linux**: take the bundled artifacts from the fork's CI (see
  [CI](#ci) above) instead of building locally.
- **macOS**: no CI job; build locally per the fork README (Homebrew Qt5 +
  `qmake` + `make`). `bundle-macos.sh` prints the exact qmake invocation if
  the binary is missing.

### Bundle for nexus-service

`./bundle-macos.sh [output-dir]` packages the locally built macOS binary
(expected at `openrgb-headless/OpenRGB`; it must already be built) into a
self-contained folder: copies it as `OpenRGB-headless`, copies the Homebrew
dylibs it links, rewrites all link paths to `@loader_path` so the folder can
be moved anywhere, and adds `LICENSE-OpenRGB.txt` + `README.txt`. Default
output is `../nexus-service/Bundled/osx-arm64/openrgb/`.

`nexus-service` consumes the artifacts from `Bundled/<rid>/openrgb/`:

| RID | Source |
|---|---|
| `win-x64` | fork CI artifact, copied in by hand |
| `osx-arm64` | `bundle-macos.sh` output (its default destination) |

`nexus-service`'s publish fails loudly if the bundle for the target RID is
missing.

---

## Branch layout in the fork

| Branch | Purpose |
|---|---|
| `main` | Mirrors `upstream/master`. Should never have headless-specific changes. Merging upstream goes into this branch first. |
| `headless` | The headless fork. Branches off `main`, contains all the deletions and edits. CI publishes binaries from this branch. **The branch we ship.** |

The two-branch setup means upstream syncs are: `git fetch upstream && git merge
upstream/master --ff-only` into `main`, then `git checkout headless && git merge
main` and resolve conflicts. The heuristic for resolving conflicts is in
`openrgb-headless/MAINTAINING.md`.

---

## What "compatibility with upstream" looks like in practice

It does **not** mean our fork is a drop-in replacement for OpenRGB - we are
shipping a different binary with a different feature set. It means:

1. **Controller updates** (new device support, protocol fixes, hardware
   detector improvements) merge with zero manual work. Upstream touches
   `Controllers/Foo/RGBController_Foo.cpp`, our merge picks it up, our build
   keeps working.
2. **NetworkServer / NetworkProtocol updates** merge with zero manual work.
   When upstream extends the SDK protocol, we get the new packet IDs.
3. **Detection / ResourceManager / ProfileManager updates** merge with zero
   manual work. These are the plumbing layers our fork depends on.
4. **Build system changes** in `OpenRGB.pro` may require manual merge work,
   but the conflict-resolution rules are documented in `MAINTAINING.md`. The
   typical case (upstream adds a new SOURCES line for a new controller) is
   trivial; the unusual case (upstream restructures the GUI build) requires
   30 seconds of judgement.
5. **GUI changes** in upstream (new dialogs, new pages, new translations) are
   irrelevant to us - we deleted the GUI. If upstream re-adds files we
   deleted, we re-delete them in the merge.

The key insight: **upstream's primary maintenance is on the GUI side, but
upstream's primary value to us is on the controller / protocol side**. The
deletions are stable file paths upstream rarely restructures, and they're all
files we never want.

---

## Where this lives in the broader nexus architecture

```
┌────────────────────────────────────────────────────────────────┐
│  nexus-service (.NET 10 Native AOT)                            │
│                                                                │
│  src/Lighting/Rgb/                                             │
│    OpenRgbController.cs     ← TCP client (AOT-safe)            │
│    OpenRgbProtocol.cs       ← binary serializers               │
│    OpenRgbProcessManager.cs ← child process supervisor         │
│    RgbBridge.cs             ← orchestration + frame fanout     │
│    ...                                                         │
│                                                                │
│  Bundled/win-x64/openrgb/   ← from the fork's CI artifact      │
│    OpenRGB-headless.exe                                        │
│    hidapi.dll / libusb-1.0.dll                                 │
│    PawnIOLib.dll            ← (csproj-injected from pawnio/)   │
│    Smbus*.bin / LpcIO.bin   ← (csproj-injected from pawnio/)   │
│    LICENSE-OpenRGB.txt                                         │
│                                                                │
│  Bundled/osx-arm64/openrgb/ ← from bundle-macos.sh             │
│    OpenRGB-headless + relinked dylibs + LICENSE                │
│                                                                │
│  Communicates via TCP loopback ──────────────┐                 │
└──────────────────────────────────────────────│─────────────────┘
                                               │
                                               ▼
                                 127.0.0.1:6742 (OpenRGB SDK)
                                               │
                                               ▼
┌────────────────────────────────────────────────────────────────┐
│  OpenRGB-headless (this fork)                                  │
│                                                                │
│  - Spawned on demand by nexus-service                          │
│  - Detects RGB hardware (HID, I2C, SMBus, serial)              │
│  - Runs the SDK server on TCP 6742                             │
│  - No GUI, no system tray, no plugins                          │
│                                                                │
│  Hardware: Razer mouse, Corsair mouse, Gigabyte mobo,          │
│  NVIDIA GPU, etc. - the full upstream set                      │
└────────────────────────────────────────────────────────────────┘
```

`Bundled/win-x64/` is updated by downloading the Windows artifact from the
fork's CI run; `Bundled/osx-arm64/` by running `bundle-macos.sh` after a
local build (see [Building](#building)).

---

## TL;DR

- The fork is **shipping today**, embedded in `nexus-service` as a child process.
- We **physically deleted** ~53k lines of GUI code from the fork. The rest is byte-identical to upstream.
- We **don't touch upstream-shared files** (controllers, networking, detection, resource management). All changes are concentrated in `OpenRGB.pro`, `startup/*.cpp`, and the deleted directories.
- We **commit to maintaining upstream compatibility** so we can keep merging new device support, protocol fixes, and hardware detector improvements from upstream. The conflict-resolution playbook is in [`openrgb-headless/MAINTAINING.md`](openrgb-headless/MAINTAINING.md).

## License

This workspace (`bundle-macos.sh`, `scripts/`, and docs) is licensed under the
**GNU Affero General Public License v3.0** (AGPL-3.0); see [`LICENSE`](LICENSE).
The headless OpenRGB fork it builds and bundles
([`hello-nexus/openrgb-headless`](https://github.com/hello-nexus/openrgb-headless))
remains under OpenRGB's GPLv2, as required by upstream.

Copyright (C) 2026 Hello Nexus
