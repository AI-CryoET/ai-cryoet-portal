// Hand-written mirror of catalog/api/schemas.py — keep in sync.

// ── Sample list / summary ────────────────────────────────────────────────

export type SampleSummary = {
  sample_id: string
  project: string
  lab_name: string | null
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  path: string | null
  warning_count: number
  // Total child-row counts intrinsic to the sample — filter-independent.
  // ``n_tomograms`` is summed across raw + post-processed tables.
  n_acquisitions: number
  n_tomograms: number
  n_tilt_series: number
  thumbnail_path: string | null
}

// ── Sample detail: typed sub-entities ────────────────────────────────────

export type ChromatinOut = {
  substrate: string | null
  linker_length_bp: number | null
  linker_pattern: number[] | null
  linker_distribution: string | null
  buffer: string | null
  salt_mM: string | null
  ptm: string | null
  histone_variants: string | null
  transcription_factors: string | null
  nucleosome_count: number | null
  dna_length_bp: number | null
  nucleosome_uM: number | null
  sequence_identity: string | null
  nucleosome_footprint: number[] | null
  linker_length_fraction: number | null
}

export type LabelOut = {
  ordinal: number
  label_target: string | null
  aunp_type: string | null
  // Polymorphic — single size or a list of sizes.
  aunp_size_nm: number | number[] | null
  conjugation: string | null
  conjugation_target: string | null
  fluorophore: string | null
  notes: string | null
}

export type FiducialOut = {
  aunp_size_nm: number | null
  vendor: string | null
  catalog_number: string | null
  product_name: string | null
  concentration_value: number | null
  concentration_unit: string | null
}

export type SimulationOut = {
  dataset_type: string | null
}

export type FreezingOut = {
  grid_type: string | null
  solution_type: string | null
  cryoprotectant: string | null
  method: string | null
  planchette_size: string | null
  spacer_thickness: string | null
}

export type MillingOut = {
  scheme: string | null
  date: string | null
  quality: string | null
}

export type MdRunOut = {
  md_run_id: string
  seed: number | null
  computer: string | null
  sample_time: number | null
  timestep: number | null
  reference_contact: string | null
  force_field_version: string | null
}

// Fields shared between raw and post-processed tomogram outputs.
type TomogramOutBase = {
  tomogram_id: string
  voxel_size: number | null
  derived_from: string[]
  image_size_x: number | null
  image_size_y: number | null
  image_size_z: number | null
  mrc_path: string | null
  zarr_path: string | null
  zarr_axes: string | null
  zarr_scale: number[] | null
}

export type RawTomogramOut = TomogramOutBase & {
  pipeline: string | null
  software: string | null
}

export type PostProcessedTomogramOut = TomogramOutBase & {
  denoising_software: string | null
  ctf_software: string | null
  missing_wedge_software: string | null
  size_bytes: number | null
}

export type AnnotationOut = {
  annotation_id: string
  type: string | null
  target_tomogram: string | null
  files: string[]
}

export type TiltSeriesOut = {
  tilt_series_id: string
  derived_from: string | null
  is_aligned: boolean | null
  alignment_software: string | null
  alignment_method: string | null
  st_path: string | null
  zarr_path: string | null
  alignment_files: string[]
  mtime: number | null
}

export type MdSourceOut = {
  md_run_id: string | null
  frame: number | null
}

// ── Scan status (freshness + thumbnail provenance) ───────────────────────
// Per-entity current-state projection surfaced on the detail pages (plan §4.6).
// A freshly-migrated entity not yet re-scanned has scan_status === null.

export type ScanOutcome = 'upserted' | 'skipped' | 'failed'

export type EntityScanStatus = {
  last_scanned_at: number
  last_changed_at: number | null
  last_outcome: ScanOutcome
  last_scan_run_id: string
}

export type AcquisitionScanStatus = EntityScanStatus & {
  thumbnail_path: string | null
  thumbnail_source_kind: 'zarr' | 'st' | 'frames' | 'none' | null
  thumbnail_source_path: string | null
  thumbnail_generated_at: number | null
  thumbnail_status: 'ok' | 'missing_source' | 'render_failed' | null
}

export type AcquisitionOut = {
  acquisition_id: string
  // acquisition.toml ([acquisition]) — researcher authored
  resolution: number | null
  tilt_spacing: number | null
  defocus_range: string | null
  energy_filter: string | null
  phase_plate: boolean | null
  microscope: string | null
  facility: string | null
  acquisition_quality: number | null
  // MDOC / frame-extension derived
  pixel_size: number | null
  dose_per_tilt: number[] | null
  total_dose: number | null
  tilt_min: number | null
  tilt_max: number | null
  tilt_axis: number | null
  tilt_angles: number[] | null
  defocus_per_image: number[] | null
  date_collected: string | null
  voltage: number | null
  energy_filter_slit_width: number | null
  frame_count: number | null
  camera: string | null
  path: string | null
  md_source: MdSourceOut | null
  raw_tomogram: RawTomogramOut | null
  post_processed_tomograms: PostProcessedTomogramOut[]
  annotations: AnnotationOut[]
  tilt_series: TiltSeriesOut[]
  scan_status: AcquisitionScanStatus | null
}

export type SampleDetail = {
  sample_id: string
  project: string
  lab_name: string | null
  data_source: string
  type: string | null
  cell_type: string | null
  description: string | null
  path: string | null
  chromatin: ChromatinOut | null
  fiducial: FiducialOut | null
  simulation: SimulationOut | null
  freezing: FreezingOut | null
  milling: MillingOut | null
  label: LabelOut[]
  md_run: MdRunOut[]
  acquisitions: AcquisitionOut[]
  thumbnail_path: string | null
  scan_status: EntityScanStatus | null
}

// ── Filters / stats / viewers ────────────────────────────────────────────

export type RangeOut = {
  min: number | null
  max: number | null
}

export type FiltersOptionsOut = {
  categorical: Record<string, string[]>
  ranges: Record<string, RangeOut>
}

export type StatsTotalsOut = {
  samples: number
  acquisitions: number
  tilt_series: number
  // Sum across raw + post-processed tomogram tables.
  tomograms: number
  annotations: number
  warnings: number
}

export type ProjectStatRow = {
  project: string
  samples: number
  acquisitions: number
  // Sum across raw + post-processed tomogram tables.
  tomograms: number
  // Sum across PostProcessedTomogramOut.size_bytes only — RawTomogram has
  // no size_bytes field in the schema.
  size_bytes: number
}

export type StatsOverviewOut = {
  totals: StatsTotalsOut
  by_project: ProjectStatRow[]
}

export type ViewerLaunchOut = {
  url: string
}

// ── Warnings / extras ─────────────────────────────────────────────────────

// Still consumed by the sample/acquisition detail pages via
// /samples/{id}/warnings. The endpoint now reads the live `issues` table but
// returns these unchanged-enough fields.
export type WarningOut = {
  id: number
  sample_id: string
  category: string
  location: string
  message: string
  detected_at: number
  scan_run_id: string
}

export type ExtrasSummaryRow = {
  entity_type: string
  key: string
  count: number
}

// ── Manage page: summary / cadence ─────────────────────────────────────────

export type ManageLatestScan = {
  started_at: number
  ended_at: number | null
  status: string
  duration: number | null
}

export type ManageSummary = {
  latest_scan: ManageLatestScan | null
  cadence_cron: string
  cadence_tz: string
  outstanding: { errors: number; warnings: number }
  // Deletion/rename events recorded in the latest completed run (§08a badge).
  deletions_latest_run: number
}

// ── Manage page: issues (outstanding + recently resolved) ───────────────────

export type IssueSeverity = 'error' | 'warning'
export type IssueScope = 'sample' | 'acquisition' | 'run'

export type IssueItem = {
  category: string
  message: string
}

// One outstanding (or recently resolved) issue group, keyed by entity +
// file_kind. `severity` is the max across the group. Per plan §9.7, the
// "still present as of" UI compares `last_seen_run_id` to the global
// `latest_run_id` to decide whether the owner was re-evaluated this scan.
export type IssueGroup = {
  scope: IssueScope
  sample_id: string | null
  acquisition_id: string | null
  md_run_id: string | null
  file_kind: string
  file_path: string | null
  severity: IssueSeverity
  issues: IssueItem[]
  first_seen_at: number
  last_seen_at: number
  last_seen_run_id: string
  latest_run_id: string | null
  latest_scan_at: number | null
  // Only present on the /resolved view.
  resolved_at?: number | null
  resolved_run_id?: string | null
}

// ── Manage page: scan runs + logs ──────────────────────────────────────────

export type ScanRun = {
  scan_run_id: string
  started_at: number
  ended_at: number | null
  status: string
  root: string
  n_upserted: number | null
  n_skipped: number | null
  n_failed: number | null
  n_new_issues: number | null
  n_resolved_issues: number | null
  n_warning_active: number | null
  n_error_active: number | null
}

export type ScanLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

export type ScanLogLine = {
  id: number
  seq: number
  ts: number
  level: ScanLogLevel
  sample_id: string | null
  message: string
}

// ── Manage page: deletion / rename audit feed (§08a/§08c) ───────────────────

export type DeletionEntityType =
  | 'sample'
  | 'acquisition'
  | 'raw_tomogram'
  | 'post_processed_tomogram'
  | 'annotation'
  | 'tilt_series'
  | 'md_source'

export type DeletionEventKind = 'deletion' | 'rename'

// One row of the append-only deletion audit feed. For `kind: "rename"`,
// `last_known_json` holds `{"renamed_from": old_id, "renamed_to": new_id}`
// instead of a row snapshot.
export type DeletionEvent = {
  id: number
  scan_run_id: string
  detected_at: number
  entity_type: DeletionEntityType
  kind: DeletionEventKind
  sample_id: string
  acquisition_id: string | null
  entity_id: string | null
  last_known_path: string | null
  last_known_json: string | null
}

export type ScanSampleOutcome = {
  sample_id: string
  outcome: ScanOutcome
  detail: string | null
}
