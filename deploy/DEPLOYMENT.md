# OpenShift Deployment

This guide covers deploying the CryoET catalog portal to an OpenShift cluster
using [Kustomize](https://kustomize.io/).

## Prerequisites

- An OpenShift cluster with `oc` access
- A cluster router (`openshift-ingress`) serving a TLS certificate for your
  hostname — the application relies on the router for edge termination and does
  not manage its own TLS secret
- Container images pushed to your registry (see
  [GitHub Actions workflow](../.github/workflows/build-images.yml))
- A way to mount the CryoET data tree into the cluster (see
  [Wiring up the data root](#wiring-up-the-data-root))

## Architecture

```
Route (ai-cryoet.int.janelia.org) — edge TLS, HTTP→HTTPS redirect
    |
    v
  nginx (8080)
    |  /api/*                      -> api      (8000)   FastAPI read API
    |  /v /neuroglancer /events ...  -> api      (8050)   in-process Neuroglancer
    |  everything else             -> frontend (3000)   TanStack Start SSR
    |
    v
  api  ──reads──>  catalog-data (read-only data tree)
       ──reads──>  catalog-db   (SQLite)        <──writes── scanner (CronJob)
       ──reads──>  thumbnails   (PNG cache)     <──writes── scanner (CronJob)

Route (mrc-ng-server.int.janelia.org) — edge TLS, HTTP→HTTPS redirect
    |
    v
  mrc-ng-server (8000) ──reads──> catalog-data (read-only data tree)
                       ──reads──> mrc-cache (pyramid cache) <──writes── scanner
```

The browser fetches Neuroglancer `precomputed` chunks straight from
mrc-ng-server (its own Route), not through nginx — so it is a second public
entrypoint, separate from the portal's.

There are four runtime components plus one batch job, plus the standalone
mrc-ng-server data service:

| Component | Image | Port(s) | Role |
|---|---|---|---|
| `nginx` | `nginxinc/nginx-unprivileged` | 8080 | Edge proxy. The only service behind the portal Route. |
| `api` | `ai-cryoet-api` | 8000, 8050 | FastAPI read API + in-process Neuroglancer server. |
| `frontend` | `ai-cryoet-frontend` | 3000 | Server-rendered React app. |
| `scanner` | `ai-cryoet-scanner` | — | CronJob: walks the data tree, rebuilds the DB + thumbnails, and precomputes the `mrc-cache` pyramid. |
| `mrc-ng-server` | `mrc-ng-server` | 8000 | Stateless service that serves tomograms to Neuroglancer over `precomputed`. Own image/repo/tag; own Route. Scalable (unlike `api`). |

## Directory Structure

```
deploy/k8s/
├── base/                    # Shared resource definitions
│   ├── kustomization.yaml
│   ├── storage.yaml         # PVCs: catalog-data, catalog-db, thumbnails, mrc-cache
│   ├── api.yaml             # FastAPI + Neuroglancer Deployment + Service
│   ├── frontend.yaml        # SSR frontend Deployment + Service
│   ├── nginx.yaml           # Edge proxy ConfigMap + Deployment + Service
│   ├── scanner.yaml         # Catalog scanner CronJob
│   ├── mrc-ng-server.yaml   # Tomogram data service Deployment + Service
│   └── routes.yaml          # OpenShift Routes (portal + mrc-ng-server, edge TLS)
└── overlays/
    ├── production/          # Production: namespace ai-cryoet
    │   ├── kustomization.yaml
    │   ├── namespace.yaml
    │   └── config.env.example   # Template for non-sensitive environment variables
    └── dev/                 # Development: namespace ai-cryoet-dev
        ├── kustomization.yaml
        ├── namespace.yaml
        └── config.env.example
```

Copy `config.env.example` to `config.env` and fill in real values. `config.env`
is gitignored and must not be committed.

Both overlays build from the same `base/`, so every command below works for
either environment — substitute the overlay path and namespace:

| | Production | Development |
|---|---|---|
| Namespace | `ai-cryoet` | `ai-cryoet-dev` |
| Overlay | `deploy/k8s/overlays/production` | `deploy/k8s/overlays/dev` |
| Route host | `ai-cryoet.int.janelia.org` | `ai-cryoet-dev.int.janelia.org` |
| Data-tree PV | `nfs-cryoet-data` | `nfs-cryoet-data-dev` |
| Scanner | Hourly | Nightly (02:00) |
| Image tags | Pinned | Pinned (bump ahead of prod to test a release) |

## Wiring up the data root

The scanner reads a large, **pre-existing** data tree (e.g.
`/groups/cryoet/cryoet/data`) and the API reads the same tree to
serve previews and launch Neuroglancer. Unlike the SQLite DB and the thumbnail
cache — which the app creates from scratch — this data already lives on storage
your cluster administrators manage.

In Kubernetes a pod can only read storage that has been explicitly handed to it
through a **PersistentVolumeClaim (PVC)** — a named request for storage. *Where*
that storage physically lives (an NFS export, a `/groups` mount, etc.) is
configured by the cluster/HPC team, not by these manifests.

`deploy/k8s/base/storage.yaml` declares a PVC named **`catalog-data-pvc`** as a
placeholder. Before deploying, take this question to the HPC/OpenShift team:

> *"How do we make `/groups/cryoet/cryoet/data` readable from pods
> in the `ai-cryoet` namespace, and what should the PVC be called?"*

They will typically do one of:

- **Bind `catalog-data-pvc` to a statically-provisioned PersistentVolume** that
  points at the existing export. In this case keep the PVC name as-is and they
  fill in the `storageClassName` / `volumeName` to match their PV.
- **Hand you an existing PVC name.** In that case either rename it to
  `catalog-data-pvc`, or change `claimName: catalog-data-pvc` to their name in
  `api.yaml` and `scanner.yaml`.

Whatever path is mounted **must equal** `CATALOG_DATA_ROOT` in `config.env` and
the `mountPath` for the `catalog-data` volume in `api.yaml` and `scanner.yaml`
(all three default to `/groups/cryoet/cryoet/data`). The scanner
records absolute paths under this root and the API validates reads against it,
so they must agree exactly.

The other two volumes (`catalog-db-pvc`, `thumbnails-pvc`) are created and
populated by the app and are shared between the API pod and the scanner pod, so
they use `ReadWriteMany`. Confirm with the HPC team that the default storage
class supports `ReadWriteMany` (NFS/CephFS do); if not, set an RWX-capable
`storageClassName` on those PVCs.

## Production deployment Steps

These steps use the production overlay. For the development environment see
[The development environment](#the-development-environment), which is the same
sequence against `overlays/dev` / `ai-cryoet-dev`.

### 1. Configure environment

```bash
cp deploy/k8s/overlays/production/config.env.example deploy/k8s/overlays/production/config.env
```

Edit `config.env`:

- `CATALOG_DATA_ROOT` — the in-cluster mount path of the data tree (must match
  the volume mountPath; see above)
- `CORS_ORIGINS` — the public URL of the portal
- The remaining values rarely change from the template.

This app has no database password, user accounts, or SMTP credentials, so there
is no `secrets.env` — only the non-sensitive `config.env`.

### 2. Create the namespace

```bash
oc apply -f deploy/k8s/overlays/production/namespace.yaml
```

### 3. Create the image pull secret for ghcr.io

The container images are hosted on GitHub Container Registry and require
authentication. Create a [Personal Access Token](https://github.com/settings/tokens)
(classic) with the `read:packages` scope, then create the pull secret. The name
must be `ghcr-pull` — that is what the `imagePullSecrets` in `base/api.yaml`,
`base/frontend.yaml` and `base/scanner.yaml` reference. Secrets are namespaced,
so **each environment needs its own copy**:

```bash
oc create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<PAT> \
  -n ai-cryoet          # or -n ai-cryoet-dev
```

### 4. TLS

The portal `cryoet` Route in `deploy/k8s/base/routes.yaml` uses edge TLS
termination without specifying a certificate, so the cluster router serves its
own configured certificate for the hostname. No per-application TLS secret is
needed. For a custom certificate, extend the Route `spec.tls` block with
`certificate`/`key`/`caCertificate` or use `externalCertificate`
(OpenShift 4.16+).

The mrc-ng-server has no Route of its own: the browser reaches it via nginx's
`/mrc-ng-server/` location on the portal host (see `deploy/nginx.conf`), so it
stays a namespace-internal Service. That path prefix + `/data` must equal
`MRCNG_BASE_URL` in `config.env` — the URL the browser fetches Neuroglancer
chunks from.

### 5. Preview the generated manifests

```bash
oc kustomize deploy/k8s/overlays/production
```

### 6. Deploy

```bash
oc apply -k deploy/k8s/overlays/production
```

### 7. Populate the catalog (first run)

On a fresh deploy the SQLite DB does not exist yet, so the API serves an empty
catalog (and some pages may error until the first scan completes). Trigger the
scanner immediately rather than waiting for the next hourly run:

```bash
oc -n ai-cryoet create job --from=cronjob/scanner scanner-initial
oc -n ai-cryoet logs -f job/scanner-initial
```

### 8. Verify

```bash
# All pods running
oc -n ai-cryoet get pods

# API logs
oc -n ai-cryoet logs -l app=api

# Routes admitted
oc -n ai-cryoet get route cryoet mrc-ng-server

# mrc-ng-server serving (health + a precomputed dataset's metadata)
oc -n ai-cryoet logs -l app=mrc-ng-server
curl -sf https://mrc-ng-server.int.janelia.org/healthz
```

Then open `https://ai-cryoet.int.janelia.org`.

## Neuroglancer in production

"View in Neuroglancer" starts an HTTP server *inside* the API process on port
8050. The frontend re-roots the viewer URL onto the page origin (it drops the
host and port the API reports), so the Neuroglancer paths must be reachable
through nginx on the same origin as the portal. The nginx ConfigMap in
`deploy/k8s/base/nginx.yaml` proxies Neuroglancer's fixed root paths (`/v`,
`/neuroglancer`, `/events`, `/state`, `/action`, `/volume_response`,
`/credentials`) to `api:8050` for exactly this reason.

Because the Neuroglancer server is process-global, the API **must** run as a
single replica with a single uvicorn worker (the image is built this way). Do
not scale the `api` Deployment above 1.

## Fileglancer write access

"Save to file share" writes authored TOML directly to the data tree through
[Fileglancer](https://github.com/JaneliaSciComp/fileglancer)'s programmatic JS
API. This app never handles a token or password for that write — see below —
but Fileglancer's server does need to be told to trust this app's origin.

### Prerequisite: allowlist this app's origin on Fileglancer

Fileglancer only accepts API calls from origins listed in its own
`api_allowed_origins` server config. This app's **exact** origins (scheme +
host + port, no path) must be added there:

```yaml
api_allowed_origins:
  - https://ai-cryoet.int.janelia.org        # prod
  - https://ai-cryoet-dev.int.janelia.org    # dev
```

This is a change to **Fileglancer's** server configuration, not to anything in
this repo — it's an ops prerequisite for whoever administers the Fileglancer
deployment, and needs to happen before Save will work from a new environment.

**Symptom if this is missed:** every Fileglancer API call fails with a `403
ForbiddenError`, and the app surfaces a message naming the allowlist as the
likely cause. If Save fails with a permission error, check this first.

### Local dev on `localhost` can't use Save

Fileglancer's session cookie is scoped to the `janelia.org` domain
(`SameSite=Lax`), so the browser will never attach it to a `localhost` origin
— no allowlist entry can fix this. Local dev relies on the **Download**
button, which stays available as a fallback on every environment (including
production, for any user who hits a 403 or prefers a manual copy).

### No secrets or credentials live in this app

Authentication is Fileglancer's own session cookie — this app stores no
tokens, passwords, or API keys of its own. If the user isn't already logged
into Fileglancer, clicking Save opens a short-lived login popup; once they
authenticate there, the save proceeds using that session.

### `VITE_FILEGLANCER_URL` build arg

The frontend image bakes in the Fileglancer base URL at build time (Vite
inlines `VITE_*` vars). It defaults to the production instance
(`https://fileglancer.int.janelia.org`) via the `FILEGLANCER_URL` Docker build
arg in `frontend/Dockerfile`. Only override it when standing up an allowlisted
dev origin that should talk to a different Fileglancer instance:

```bash
docker build --build-arg FILEGLANCER_URL=https://fileglancer-dev.int.janelia.org \
  -f frontend/Dockerfile frontend
```

## Updating the Application

Push a `v*.*.*` git tag from `main` to build and publish new images (see the
[build workflow](../.github/workflows/build-images.yml)):

```bash
git checkout main && git pull
git tag v1.0.0
git push origin v1.0.0
```

This builds and pushes all three images (`ai-cryoet-api`, `ai-cryoet-frontend`,
`ai-cryoet-scanner`) to `ghcr.io/ai-cryoet/`.

Don't forget to draft a new release to go along with the tag: https://github.com/AI-CryoET/ai-cryoet-portal/releases/new. Auto-generate the notes to include all the PRs since the last tag.

Then pin the new tag in the overlay's `kustomization.yaml`. Note: the build
workflow's `metadata-action` strips the leading `v`, so a `v1.0.0` git tag
publishes image tag `1.0.0` (without the `v`) — use that here:

```yaml
images:
  - name: ghcr.io/ai-cryoet/ai-cryoet-api
    newTag: "1.0.0"
  - name: ghcr.io/ai-cryoet/ai-cryoet-frontend
    newTag: "1.0.0"
  - name: ghcr.io/ai-cryoet/ai-cryoet-scanner
    newTag: "1.0.0"
```

Then `oc apply -k deploy/k8s/overlays/production`. Pushing a `v*.*.*` git tag builds and
publishes all three images (see the workflow).

**mrc-ng-server is versioned separately.** Its image is built and tagged in its
own repo ([mrc-ng-server](https://github.com/JaneliaSciComp/mrc-ng-server)), not
by this repo's workflow, so it carries its own `0.x` tag independent of the
portal's `1.x`. To update it, bump only its entry in the overlay:

```yaml
  - name: ghcr.io/janeliascicomp/mrc-ng-server
    newTag: "0.1.2"
```

## The development environment

`deploy/k8s/overlays/dev` deploys the same base into the **`ai-cryoet-dev`**
namespace at `https://ai-cryoet-dev.int.janelia.org`. It reads the *same*
read-only NFS data tree as production (every mount of it is flagged `readOnly`,
so dev cannot corrupt it) but owns its own catalog DB, thumbnail, MD-preview and
pyramid-cache volumes, so a broken scan or schema change in dev never touches
production.

### One-time setup

1. **DNS.** `ai-cryoet-dev.int.janelia.org` must resolve to the cluster router
   (the same address `ai-cryoet.int.janelia.org` points at). The `int` zone is
   internal-only split-horizon, so this is a request to the network team — the
   Route will be admitted by the router before DNS exists, but browsers will not
   reach it until the record is in place.
2. **Config.** `cp deploy/k8s/overlays/dev/config.env.example
   deploy/k8s/overlays/dev/config.env` (gitignored; the checked-in example
   already carries the dev hostnames).
3. **Namespace.** `oc apply -f deploy/k8s/overlays/dev/namespace.yaml`
4. **Pull secret.** Create `ghcr-pull` in `ai-cryoet-dev` — see
   [step 3](#3-create-the-image-pull-secret-for-ghcrio). Secrets do not cross
   namespaces, so production's copy does not count.
5. **Fileglancer allowlist.** "Save to file share" will 403 from the dev origin
   until `https://ai-cryoet-dev.int.janelia.org` is added to Fileglancer's
   `api_allowed_origins` — see [Fileglancer write
   access](#prerequisite-allowlist-this-apps-origin-on-fileglancer). Download
   works regardless.
6. **Deploy and seed.**
   ```bash
   oc apply -k deploy/k8s/overlays/dev
   oc -n ai-cryoet-dev create job --from=cronjob/scanner scanner-initial
   oc -n ai-cryoet-dev logs -f job/scanner-initial
   ```
   The nightly CronJob keeps it fresh after that; the manual job avoids waiting
   until 02:00 for a catalog.

### Using it to stage a release

The dev overlay pins image tags exactly as production does, which is the point:
bump the tags in `deploy/k8s/overlays/dev/kustomization.yaml` to a new release,
`oc apply -k deploy/k8s/overlays/dev`, verify, and only then bump production.
Dev is deliberately *not* tracking `:latest` — the build workflow publishes only
on `v*.*.*` tags, so `:latest` means "newest release" and would make dev's
version depend on when a pod last restarted.

## Adding another environment

Copy `overlays/dev` and change the namespace, the Route host, and the two
hostnames in `config.env`. One non-obvious step is mandatory:

> **Give the data-tree PersistentVolume a unique name.** PersistentVolumes are
> **cluster-scoped** and bind exclusively to one PVC. `base/storage.yaml`
> declares `nfs-cryoet-data`, which is already Bound to
> `ai-cryoet/catalog-data-pvc`; a second environment reusing that name gets a
> `catalog-data-pvc` stuck **Pending** forever, and the api/scanner/mrc-ng-server
> pods never schedule. The dev overlay patches the PV to `nfs-cryoet-data-dev`
> and repoints its PVC's `volumeName` to match — copy both patches. (`volumeName`
> is not a reference Kustomize rewrites automatically, so the second patch is not
> redundant.) Pointing several PVs at the same NFS export is fine: an `nfs` PV is
> mount instructions, not an exclusive lease.

Also carry over the `storageClassName: ocs-storagecluster-cephfs` patches. The
base PVCs omit the class because it is cluster-specific, and this cluster's
default (`ocs-storagecluster-ceph-rbd`) is RBD block storage that rejects the
`ReadWriteMany` these shared volumes require.

## Troubleshooting

```bash
# Events and status for a pod
oc -n ai-cryoet describe pod <pod-name>

# CronJob run history
oc -n ai-cryoet get jobs

# Run the scanner on demand
oc -n ai-cryoet create job --from=cronjob/scanner scanner-manual

# Route status (admitted, host, TLS)
oc -n ai-cryoet describe route cryoet

# Inspect the catalog DB inside the API pod
oc -n ai-cryoet exec deploy/api -- ls -la /db /thumbnails
```

**API returns 500s after a schema change.** The SQLite DB in the `catalog-db`
volume predates the current ORM schema. Re-run the scanner; if it still fails,
the volume can be wiped (delete and recreate `catalog-db-pvc`) and rescanned —
the DB is fully rebuildable from the data tree.

**Scanner sees no data / empty catalog.** The `catalog-data` volume is not
mounted at the path the scanner expects. Confirm `CATALOG_DATA_ROOT`, the volume
`mountPath`, and what the HPC team actually exported all point at the same tree
(see [Wiring up the data root](#wiring-up-the-data-root)).
