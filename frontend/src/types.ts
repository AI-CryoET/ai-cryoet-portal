// Thin, stable-named re-exports over `types.gen.ts` (generated from
// catalog/api/schemas.py by `pixi run gen-frontend-types` — see
// `catalog/api/generate_openapi.py` + `openapi-typescript`). Don't hand-edit
// field shapes here; re-run the codegen instead.
//
// A few fields are typed `str` (not a Python Enum) on the backend, so
// openapi-typescript widens them to `string`. Those are narrowed back to a
// literal union below, where the frontend relies on it (dropdown options,
// exhaustive display-mapping) — the backend doesn't enforce these lists, so
// keeping a new backend value in sync here is still a manual step.

import type { components } from './types.gen';

type Schemas = components['schemas'];

// FastAPI always serializes every declared response field (a Pydantic field
// with a default is still emitted, just possibly `null`) — but because it
// *can* be omitted per the JSON Schema spec, openapi-typescript marks any
// field with a default as optional (`?:`), recursively through every nested
// entity. `Defined` restores the old hand-written contract (every field
// present, at every nesting level; only the value may be `null`) so
// consuming code doesn't need `| undefined` handling everywhere.
type Defined<T> = T extends (infer U)[]
  ? Defined<U>[]
  : T extends object
    ? { [K in keyof T]-?: Defined<T[K]> }
    : T;

// ── Sample list / summary ────────────────────────────────────────────────

export type SampleSummary = Defined<Schemas['SampleSummary']>;

// ── Sample detail: typed sub-entities ────────────────────────────────────

export type ChromatinOut = Defined<Schemas['ChromatinOut']>;
export type LabelOut = Defined<Schemas['LabelOut']>;
export type FiducialOut = Defined<Schemas['FiducialOut']>;
export type SimulationOut = Defined<Schemas['SimulationOut']>;
export type FreezingOut = Defined<Schemas['FreezingOut']>;
export type MillingOut = Defined<Schemas['MillingOut']>;
export type MdRunOut = Defined<Schemas['MdRunOut']>;
export type RawTomogramOut = Defined<Schemas['RawTomogramOut']>;
export type PostProcessedTomogramOut = Defined<
  Schemas['PostProcessedTomogramOut']
>;
export type AnnotationOut = Defined<Schemas['AnnotationOut']>;
export type TiltSeriesOut = Defined<Schemas['TiltSeriesOut']>;
export type MdSourceOut = Defined<Schemas['MdSourceOut']>;

// ── Scan status (freshness + thumbnail provenance) ───────────────────────
// Per-entity current-state projection surfaced on the detail pages (plan §4.6).
// A freshly-migrated entity not yet re-scanned has scan_status === null.

export type ScanOutcome = 'upserted' | 'skipped' | 'failed';

export type EntityScanStatus = Omit<
  Defined<Schemas['EntityScanStatus']>,
  'last_outcome'
> & {
  last_outcome: ScanOutcome;
};

export type AcquisitionScanStatus = Omit<
  Defined<Schemas['AcquisitionScanStatus']>,
  'last_outcome' | 'thumbnail_source_kind' | 'thumbnail_status'
> & {
  last_outcome: ScanOutcome;
  thumbnail_source_kind: 'zarr' | 'st' | 'frames' | 'none' | null;
  thumbnail_status: 'ok' | 'missing_source' | 'render_failed' | null;
};

export type AcquisitionOut = Defined<
  Omit<Schemas['AcquisitionOut'], 'scan_status'>
> & {
  scan_status: AcquisitionScanStatus | null;
};
export type SampleDetail = Defined<
  Omit<Schemas['SampleDetail'], 'scan_status' | 'acquisitions'>
> & {
  scan_status: EntityScanStatus | null;
  acquisitions: AcquisitionOut[];
};

// ── Filters / stats / viewers ────────────────────────────────────────────

export type RangeOut = Defined<Schemas['RangeOut']>;
export type FiltersOptionsOut = Defined<Schemas['FiltersOptionsOut']>;
export type StatsTotalsOut = Defined<Schemas['StatsTotalsOut']>;
export type ProjectStatRow = Defined<Schemas['ProjectStatRow']>;
export type StatsOverviewOut = Defined<Schemas['StatsOverviewOut']>;
export type ViewerLaunchOut = Defined<Schemas['ViewerLaunchOut']>;

// ── Warnings / extras ─────────────────────────────────────────────────────

export type WarningOut = Defined<Schemas['WarningOut']>;
export type ExtrasSummaryRow = Defined<Schemas['ExtrasSummaryRow']>;

// ── Manage page: summary / cadence ─────────────────────────────────────────

export type ManageLatestScan = Defined<Schemas['LatestScanInfo']>;
export type ManageSummary = Defined<
  Omit<Schemas['ManageSummary'], 'latest_scan'>
> & {
  latest_scan: ManageLatestScan | null;
};

// ── Manage page: issues (outstanding + recently resolved) ───────────────────

export type IssueSeverity = 'error' | 'warning';
export type IssueScope = 'sample' | 'acquisition' | 'run';
export type IssueItem = Defined<Schemas['IssueItem']>;

// One outstanding (or recently resolved) issue group, keyed by entity +
// file_kind. `severity` is the max across the group. Per plan §9.7, the
// "still present as of" UI compares `last_seen_run_id` to the global
// `latest_run_id` to decide whether the owner was re-evaluated this scan.
export type IssueGroup = Omit<
  Defined<Schemas['IssueGroup']>,
  'scope' | 'severity'
> & {
  scope: IssueScope;
  severity: IssueSeverity;
};

// ── Manage page: scan runs + logs ──────────────────────────────────────────

export type ScanRun = Defined<Schemas['ScanRun']>;

export type ScanLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

export type ScanLogLine = Omit<Defined<Schemas['ScanLogLine']>, 'level'> & {
  level: ScanLogLevel;
};

// ── Manage page: deletion / rename audit feed (§08a/§08c) ───────────────────

export type DeletionEntityType =
  | 'sample'
  | 'acquisition'
  | 'raw_tomogram'
  | 'post_processed_tomogram'
  | 'annotation'
  | 'tilt_series'
  | 'md_source';

export type DeletionEventKind = 'deletion' | 'rename';

// One row of the append-only deletion audit feed. For `kind: "rename"`,
// `last_known_json` holds `{"renamed_from": old_id, "renamed_to": new_id}`
// instead of a row snapshot.
export type DeletionEvent = Omit<
  Defined<Schemas['DeletionEvent']>,
  'entity_type' | 'kind'
> & {
  entity_type: DeletionEntityType;
  kind: DeletionEventKind;
};

export type ScanSampleOutcome = Omit<
  Defined<Schemas['ScanSampleOutcomeOut']>,
  'outcome'
> & {
  outcome: ScanOutcome;
};
