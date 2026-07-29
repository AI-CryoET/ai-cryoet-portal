# Neuroglancer viewer memory release — design

- **Date:** 2026-07-29
- **Status:** Draft for spec review
- **Branch context:** follows the Phase 1 stopgap
  (`2026-07-28-neuroglancer-viewer-concurrency-stopgap-design.md`), which
  reverted the load path to an in-RAM copy and bumped the api pod to 24 Gi.

## Problem

Phase 1 fixed serving *speed* (in-RAM volumes, no NFS on the hot path) but
introduced a *memory* problem in production:

- Opening tabs makes resident memory climb monotonically; ~8 tabs reaches
  ~20 GB of the 24 Gi limit and the next launch hangs in reclaim.
- **Closing tabs frees nothing** — memory only ever goes up.

Phase 1 §5 assumed evicting a viewer "drops the ref → GC frees it." That is
false, and eviction does not even fire below `MAX_VIEWERS` — so nothing
reclaims memory in normal use.

## Root cause (verified on the live pod)

Each viewer's numpy array has **two independent strong holders**. Releasing one
frees nothing; both must be released:

1. **`viewer.volume_manager.volumes[token]`** — a `LocalVolumeManager` dict
   inside the `Viewer`, strong ref to the `LocalVolume` → the array.
2. **`_load_mrc_volume_cached` (`lru_cache`, `_mrc.py`)** — holds the *same*
   array object in its `(data, voxel_size, axis_order)` tuple, keyed
   `(path, mtime)`, on an independent LRU.

`neuroglancer.server.global_server.viewers` is a `WeakValueDictionary`, so the
process-global server does **not** pin viewers — good. Dropping our
`active_viewers` reference is defeated only by the two holders above.

Measured (`/proc/self/statm`, ~1 GiB touched array, 1 viewer):

| step | RSS | `volume_manager.volumes` |
|---|---|---|
| after building viewer | 1074 MB | 1 |
| after `with viewer.txn() as s: s.layers.clear()` | 51 MB | 0 |

Clearing the viewer's layers makes the volume manager drop its entry
synchronously; a following `gc.collect()` breaks the `Viewer ↔ manager` cycle
and `malloc_trim(0)` returns freed pages to the OS. **No neuroglancer patch
required** — the fix uses public API.

## Goals / Non-goals

**Goals**
- Memory is reclaimed when viewers go away, via three triggers: **eviction**
  (cap exceeded), **idle sweep** (viewer unused past a TTL), and manual
  teardown.
- Steady-state resident memory is *bounded* and *recedes* — the pod never
  climbs to the limit under normal use.
- Minimal code; no neuroglancer fork, no frontend rework, no extra process.

**Non-goals**
- Instant release the moment a browser tab closes — not achievable here (see
  below); deferred to Phase 2.
- Multi-process neuroglancer pool / large-volume performance — Phase 2.

## Why there is no true "tab-close" event

"View in Neuroglancer" opens a **new browser tab pointed at the process-global
neuroglancer server** (`NeuroglancerButton.tsx`: `window.open` then
`w.location.href = <neuroglancer url>`). In production that page is served on
neuroglancer's own port — a foreign origin whose HTML we do not control. So:

- We cannot inject a `beforeunload` / `pagehide` handler into that page.
- A cross-origin `navigator.sendBeacon` back to the API will not fire.

The only server-visible liveness signals are the SSE `/events` connection
(owned by neuroglancer internals — fragile to hook) and client activity
reflected in `viewer.config_state.state_generation`, which increments whenever
the browser pushes state (pan / zoom / scroll). The idle sweep uses the latter.
A true instant close event requires reverse-proxying neuroglancer's SSE stream
through the API so we observe the disconnect — that is Phase 2.

## Design

Three triggers share one teardown primitive.

### 0. `teardown_viewer` (shared primitive, `_neuroglancer.py`)

```python
def teardown_viewer(viewer) -> None:
    """Release a viewer's volume RAM. Runs on the threadpool (txn blocks)."""
    with viewer.txn() as s:
        s.layers.clear()          # volume_manager drops the LocalVolume
    gc.collect()                  # break the Viewer <-> manager cycle
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)   # glibc only; return to OS
    except OSError:
        pass
```

Tearing down breaks that still-open tab (there is no per-viewer `.stop()`);
this is the same trade-off today's LRU eviction already accepts.

### 1. Release the array's second holder (the load cache)

Clearing layers only releases holder (1). The array stays resident while
`_load_mrc_volume_cached` still holds it. Bound that cache to the RAM budget:

- Set the cache `maxsize` = the viewer cap (see §4), **not** 12 (was aligned to
  the old cheap-mmap-era cap).

Then steady-state resident memory ≈ `max(cache_maxsize, MAX_VIEWERS) × volume`,
regardless of how many tabs have been opened over time. A torn-down viewer's
RAM returns once the array also ages out of this cache. (A precise alternative —
reference-count arrays by live viewers and evict the cache entry on last
teardown — is more code and only matters if RAM must hit zero the instant the
last tab of a volume closes; not needed for the stopgap.)

### 2. Trigger: eviction (cap exceeded)

In `launch_viewer_in_registry` (`tomograms.py`), replace the bare `popitem`
with a collect-under-lock / teardown-off-lock pattern (the txn takes its own
lock — do not hold the asyncio lock across it):

```python
evicted = []
async with lock:
    registry[key] = viewer
    while len(registry) > max_viewers:
        evicted.append(registry.popitem(last=False)[1])
for v in evicted:
    await run_in_threadpool(teardown_viewer, v)
```

### 3. Trigger: use-aware idle sweep (gated on memory pressure)

Each `active_viewers` entry carries `last_active` (monotonic) and the last-seen
`state_generation`. A background task started in the app lifespan (`main.py`)
sweeps on an interval, refreshing liveness every pass, and tears down anything
idle past the TTL — **but only while the pod is under memory pressure**.
Freeing an idle viewer is only worth doing when RAM is tight; below the
threshold, idle viewers stay resident (fast re-open) and the LRU cap remains
the hard bound.

Pressure = anon memory as a fraction of the cgroup v2 limit
(`/sys/fs/cgroup/memory.stat` `anon` ÷ `memory.max`). Anon is the right signal:
it's the unreclaimable memory the viewer arrays + base process hold. We ignore
`memory.current`, which also counts reclaimable NFS page cache the kernel drops
on its own — so page cache alone never reads as pressure. Off cgroup v2
(dev/tests) the probe returns 0.0, so the sweep never reclaims.

```python
async def sweep_idle_viewers(app, interval, ttl, pressure_ratio):
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        under_pressure = _memory_usage_ratio() >= pressure_ratio
        stale = []
        async with app.state.active_viewers_lock:
            for key, e in list(app.state.active_viewers.items()):
                gen = e.viewer.config_state.state_generation
                if gen != e.last_gen:            # client interacted -> alive
                    e.last_gen, e.last_active = gen, now
                elif under_pressure and now - e.last_active > ttl:
                    stale.append((key, e.viewer))
            for key, _v in stale:
                del app.state.active_viewers[key]
        for _key, v in stale:                    # off-lock, threadpool
            await run_in_threadpool(teardown_viewer, v)
```

This means the registry entry is no longer a bare viewer; store a small
dataclass `ViewerEntry(viewer, last_active, last_gen)`. Set `last_active` at
launch. Fallback if the activity signal proves unreliable: drop the
`state_generation` check and cull purely on age since launch.

### 4. Resource sizing (config: `cryoet-config`)

| Setting | Value | Rationale |
|---|---|---|
| `NEUROGLANCER_MAX_VIEWERS` | **8** | Phase 1's 12 assumed anon-only; the cgroup caps anon **+** page cache together. At ~1.3-1.5 GB/volume, 8 fits with headroom; ~10-12 is the practical ceiling. |
| load cache `maxsize` | **8** | matches the viewer cap so it isn't a second, larger memory pool. |
| `NEUROGLANCER_VIEWER_TTL_SECONDS` | **3600** (1 hr) | idle threshold; only reclaimed under memory pressure. |
| `NEUROGLANCER_SWEEP_INTERVAL_SECONDS` | **60** | sweep cadence. |
| `NEUROGLANCER_MEMORY_PRESSURE_RATIO` | **0.8** | reclaim idle viewers only once anon usage ≥ this fraction of the cgroup limit. |

Bound after these changes: resident volumes ≈ 8 × ~1.3-1.5 GB ≈ 11-12 GB —
under 24 Gi with ~3 GB base process and room left for NFS page cache.

## Honest limitations

- Idle memory is only reclaimed **under pressure**: below the threshold, closed
  tabs' viewers stay resident until the LRU cap evicts them. This is intended —
  no reclamation work while RAM is plentiful. Under pressure, memory returns
  within `TTL + interval` of the **last interaction**, and an idle-but-open tab
  can be culled (its viewer breaks — acceptable for a read-only portal).
- Instant, precise release on real disconnect is Phase 2 (proxy the SSE
  stream).

## Testing

- **Unit — teardown frees RAM:** build a viewer over a touched array, record RSS
  via `/proc/self/statm`, call `teardown_viewer`, assert
  `viewer.volume_manager.volumes` is empty and RSS drops by ~the array size.
  This pins the layer/volume-manager coupling so a neuroglancer bump can't
  silently regress it.
- **Unit — eviction tears down:** push past `MAX_VIEWERS`, assert the oldest is
  gone from the registry and its volume freed.
- **Unit — idle sweep:** set an entry's `last_active` into the past, run one
  sweep pass, assert it is removed and its volume freed; then bump
  `state_generation` and assert an active entry survives.
- **Regression:** existing `test_api_neuroglancer`, tilt-series, and annotations
  suites stay green (they patch `view_neuroglancer`).
- **Manual (prod):** open ~8 tabs, confirm memory bounds at ~8 GB not ~20 GB;
  close/idle them and confirm memory recedes within the TTL (`oc adm top pod`).

## Rollout / deploy

- Code change (touches `src/`): new image tag + overlay `newTag` bump.
- Config changes land in `cryoet-config`; the api Deployment uses
  `strategy: Recreate`, so applying recreates the pod (brief downtime, viewers
  reset — expected).

## Phase 2 (unchanged, separate spec)

Multi-process neuroglancer pool with the API reverse-proxying neuroglancer
paths (including the SSE `/events` stream). That proxy is also what enables
**instant** memory release on real tab-close — the precise version of the idle
sweep here.

**Why Phase 2 alone would *not* fix what we are seeing.** Phase 2 targets a
*throughput* problem (GIL / serving serialization at 25–50 concurrent tabs),
not the *memory* problem in this doc:

- **It does not reduce memory, and likely increases it.** Total RAM to hold N
  in-RAM volumes is the same whether served by one process or K. Worse, the
  shared load cache is *per-process*, so the same tomogram opened in two
  subprocesses becomes two copies — splitting for parallelism gives up the
  cross-viewer dedup that is our only memory saving.
- **It does not, by itself, release anything.** Volumes stay resident in each
  subprocess until *something* tears them down. Phase 2 needs the exact same
  `teardown_viewer` + reclaim triggers specced here (eviction, idle) — the
  reverse proxy only adds a *more precise* trigger (real disconnect), it is not
  a reclaim mechanism on its own.
- **It is aimed at a load we are nowhere near.** Its trigger is >12 distinct
  volumes / 25–50 concurrent tabs; we exhaust memory at ~6–8. Building the
  multi-process machinery would not move the ceiling we are actually hitting.

So this doc's changes are the prerequisite. Phase 2 is the follow-on for
concurrency and for turning the idle *timeout* into an instant close event —
only worth it once memory is bounded and reclaimed.
