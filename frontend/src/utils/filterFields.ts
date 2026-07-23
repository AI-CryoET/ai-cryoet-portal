// Filter field registry — single source of truth for the metadata filters.
//
// Hand-mirrored from src/catalog/api/filter_fields.py. There is no codegen
// (this repo has no cross-language build step; types.ts already hand-mirrors
// schemas.py). tests/catalog/test_filter_fields_drift.py pins key/kind/table/
// column parity with the Python registry, so keep one FIELD object per line
// with all of key/kind/table/column present (the drift test regexes this file).

export type FieldEntity = 'sample' | 'acquisition';
export type FieldKind = 'text' | 'range' | 'boolean' | 'existence';

export interface Field {
  key: string; // URL param base; range fields emit `${key}_min` / `${key}_max`
  label: string;
  entity: FieldEntity;
  group: string;
  kind: FieldKind;
  table: string; // ORM __tablename__ (sample-direct fields use 'samples')
  column: string; // ORM column; for 'existence' a predicate id string
  gating?: boolean; // true on data_source / project (gating controls)
}

export interface Group {
  section: FieldEntity;
  id: string;
  title: string;
  appliesTo?: 'experimental' | 'simulation';
  requiresProject?: 'chromatin';
  fields: Field[];
}

export const GROUPS: Group[] = [
  // ---- Section A — Sample properties ------------------------------------
  {
    section: 'sample',
    id: 'general',
    title: 'General',
    fields: [
      { key: 'lab_name', label: 'Lab', entity: 'sample', group: 'general', kind: 'text', table: 'samples', column: 'lab_name' },
      { key: 'data_source', label: 'Data source', entity: 'sample', group: 'general', kind: 'text', table: 'samples', column: 'data_source', gating: true },
      { key: 'project', label: 'Project', entity: 'sample', group: 'general', kind: 'text', table: 'samples', column: 'project', gating: true },
      { key: 'type', label: 'Type', entity: 'sample', group: 'general', kind: 'text', table: 'samples', column: 'type' },
      { key: 'cell_type', label: 'Cell type', entity: 'sample', group: 'general', kind: 'text', table: 'samples', column: 'cell_type' },
    ],
  },
  {
    section: 'sample',
    id: 'chromatin',
    title: 'Chromatin',
    requiresProject: 'chromatin',
    fields: [
      { key: 'substrate', label: 'Substrate', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'substrate' },
      { key: 'linker_length_bp', label: 'Linker length (bp)', entity: 'sample', group: 'chromatin', kind: 'range', table: 'chromatin', column: 'linker_length_bp' },
      // ponytail: data-derived categorical (stored list[int] stringified, matched IN verbatim); upgrade to json_each only if needed.
      { key: 'linker_pattern', label: 'Linker pattern', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'linker_pattern' },
      { key: 'linker_distribution', label: 'Linker distribution', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'linker_distribution' },
      { key: 'buffer', label: 'Buffer', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'buffer' },
      { key: 'salt_mM', label: 'Salt (mM)', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'salt_mM' },
      { key: 'ptm', label: 'PTM', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'ptm' },
      { key: 'histone_variants', label: 'Histone variants', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'histone_variants' },
      { key: 'transcription_factors', label: 'Transcription factors', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'transcription_factors' },
      { key: 'nucleosome_count', label: 'Nucleosome count', entity: 'sample', group: 'chromatin', kind: 'range', table: 'chromatin', column: 'nucleosome_count' },
      { key: 'dna_length_bp', label: 'DNA length (bp)', entity: 'sample', group: 'chromatin', kind: 'range', table: 'chromatin', column: 'dna_length_bp' },
      { key: 'nucleosome_uM', label: 'Nucleosome (uM)', entity: 'sample', group: 'chromatin', kind: 'range', table: 'chromatin', column: 'nucleosome_uM' },
      { key: 'sequence_identity', label: 'Sequence identity', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'sequence_identity' },
      // ponytail: data-derived categorical (stored list[int] stringified, matched IN verbatim).
      { key: 'nucleosome_footprint', label: 'Nucleosome footprint', entity: 'sample', group: 'chromatin', kind: 'text', table: 'chromatin', column: 'nucleosome_footprint' },
      { key: 'linker_length_fraction', label: 'Linker length fraction', entity: 'sample', group: 'chromatin', kind: 'range', table: 'chromatin', column: 'linker_length_fraction' },
    ],
  },
  {
    section: 'sample',
    id: 'labels',
    title: 'Labels',
    appliesTo: 'experimental',
    fields: [
      { key: 'label_target', label: 'Label target', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'label_target' },
      { key: 'aunp_type', label: 'AuNP type', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'aunp_type' },
      // ponytail: data-derived categorical (stored float|list[float], matched IN verbatim — pick-list not range); swap to numeric range if needed.
      { key: 'label_aunp_size_nm', label: 'AuNP size (nm)', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'aunp_size_nm' },
      { key: 'conjugation', label: 'Conjugation', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'conjugation' },
      { key: 'conjugation_target', label: 'Conjugation target', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'conjugation_target' },
      { key: 'fluorophore', label: 'Fluorophore', entity: 'sample', group: 'labels', kind: 'text', table: 'labels', column: 'fluorophore' },
    ],
  },
  {
    section: 'sample',
    id: 'fiducial',
    title: 'Fiducial AuNP',
    appliesTo: 'experimental',
    fields: [
      { key: 'fiducial_aunp_size_nm', label: 'AuNP size (nm)', entity: 'sample', group: 'fiducial', kind: 'range', table: 'fiducial', column: 'aunp_size_nm' },
      { key: 'vendor', label: 'Vendor', entity: 'sample', group: 'fiducial', kind: 'text', table: 'fiducial', column: 'vendor' },
      { key: 'catalog_number', label: 'Catalog number', entity: 'sample', group: 'fiducial', kind: 'text', table: 'fiducial', column: 'catalog_number' },
      { key: 'product_name', label: 'Product name', entity: 'sample', group: 'fiducial', kind: 'text', table: 'fiducial', column: 'product_name' },
      { key: 'concentration_value', label: 'Concentration', entity: 'sample', group: 'fiducial', kind: 'range', table: 'fiducial', column: 'concentration_value' },
      { key: 'concentration_unit', label: 'Concentration unit', entity: 'sample', group: 'fiducial', kind: 'text', table: 'fiducial', column: 'concentration_unit' },
    ],
  },
  {
    section: 'sample',
    id: 'freezing',
    title: 'Freezing',
    appliesTo: 'experimental',
    fields: [
      { key: 'grid_type', label: 'Grid type', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'grid_type' },
      { key: 'solution_type', label: 'Solution type', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'solution_type' },
      { key: 'cryoprotectant', label: 'Cryoprotectant', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'cryoprotectant' },
      { key: 'freezing_method', label: 'Method', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'method' },
      { key: 'planchette_size', label: 'Planchette size', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'planchette_size' },
      { key: 'spacer_thickness', label: 'Spacer thickness', entity: 'sample', group: 'freezing', kind: 'text', table: 'freezing', column: 'spacer_thickness' },
    ],
  },
  {
    section: 'sample',
    id: 'milling',
    title: 'Milling',
    appliesTo: 'experimental',
    fields: [
      { key: 'milling_scheme', label: 'Scheme', entity: 'sample', group: 'milling', kind: 'text', table: 'milling', column: 'scheme' },
      { key: 'milling_quality', label: 'Quality', entity: 'sample', group: 'milling', kind: 'text', table: 'milling', column: 'quality' },
    ],
  },
  {
    section: 'sample',
    id: 'simulation',
    title: 'Simulation',
    appliesTo: 'simulation',
    fields: [
      { key: 'dataset_type', label: 'Dataset type', entity: 'sample', group: 'simulation', kind: 'text', table: 'simulation', column: 'dataset_type' },
    ],
  },
  // ---- Section B — Acquisition properties -------------------------------
  {
    section: 'acquisition',
    id: 'general',
    title: 'General',
    fields: [
      { key: 'resolution', label: 'Resolution', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'resolution' },
      { key: 'tilt_spacing', label: 'Tilt spacing', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'tilt_spacing' },
      { key: 'defocus_range', label: 'Defocus range', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'defocus_range' },
      { key: 'energy_filter', label: 'Energy filter', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'energy_filter' },
      { key: 'phase_plate', label: 'Phase plate', entity: 'acquisition', group: 'general', kind: 'boolean', table: 'acquisitions', column: 'phase_plate' },
      { key: 'microscope', label: 'Microscope', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'microscope' },
      { key: 'facility', label: 'Facility', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'facility' },
      { key: 'acquisition_quality', label: 'Acquisition quality', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'acquisition_quality' },
      { key: 'pixel_size', label: 'Pixel size', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'pixel_size' },
      { key: 'total_dose', label: 'Total dose', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'total_dose' },
      { key: 'tilt_min', label: 'Tilt min', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'tilt_min' },
      { key: 'tilt_max', label: 'Tilt max', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'tilt_max' },
      { key: 'tilt_axis', label: 'Tilt axis', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'tilt_axis' },
      { key: 'voltage', label: 'Voltage', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'voltage' },
      { key: 'energy_filter_slit_width', label: 'Energy filter slit width', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'energy_filter_slit_width' },
      { key: 'frame_count', label: 'Frame count', entity: 'acquisition', group: 'general', kind: 'range', table: 'acquisitions', column: 'frame_count' },
      { key: 'camera', label: 'Camera', entity: 'acquisition', group: 'general', kind: 'text', table: 'acquisitions', column: 'camera' },
    ],
  },
  {
    section: 'acquisition',
    id: 'tilt_series',
    title: 'Tilt series',
    fields: [
      // existence: column is a predicate id. has_unaligned_tilt_series -> tilt_series WHERE is_aligned IS NOT TRUE
      { key: 'has_unaligned_tilt_series', label: 'Has unaligned tilt series', entity: 'acquisition', group: 'tilt_series', kind: 'existence', table: 'tilt_series', column: 'has_unaligned_tilt_series' },
      // has_aligned_tilt_series -> tilt_series WHERE is_aligned IS TRUE
      { key: 'has_aligned_tilt_series', label: 'Has aligned tilt series', entity: 'acquisition', group: 'tilt_series', kind: 'existence', table: 'tilt_series', column: 'has_aligned_tilt_series' },
      // has_tilt_series_zarr -> tilt_series WHERE zarr_path IS NOT NULL
      { key: 'has_tilt_series_zarr', label: 'Has tilt series Zarr', entity: 'acquisition', group: 'tilt_series', kind: 'existence', table: 'tilt_series', column: 'has_tilt_series_zarr' },
    ],
  },
  {
    section: 'acquisition',
    id: 'tomograms',
    title: 'Tomograms',
    fields: [
      // has_raw_tomogram -> raw_tomograms exists
      { key: 'has_raw_tomogram', label: 'Has raw tomogram', entity: 'acquisition', group: 'tomograms', kind: 'existence', table: 'raw_tomograms', column: 'has_raw_tomogram' },
      // has_post_processed_tomogram -> post_processed_tomograms exists
      { key: 'has_post_processed_tomogram', label: 'Has post-processed tomogram', entity: 'acquisition', group: 'tomograms', kind: 'existence', table: 'post_processed_tomograms', column: 'has_post_processed_tomogram' },
      // has_tomogram_zarr -> (raw UNION post) WHERE zarr_path IS NOT NULL; nominal table raw_tomograms, Phase 1 ORs both.
      { key: 'has_tomogram_zarr', label: 'Has tomogram Zarr', entity: 'acquisition', group: 'tomograms', kind: 'existence', table: 'raw_tomograms', column: 'has_tomogram_zarr' },
    ],
  },
  {
    section: 'acquisition',
    id: 'annotations',
    title: 'Annotations',
    fields: [
      { key: 'annotation_type', label: 'Annotation type', entity: 'acquisition', group: 'annotations', kind: 'text', table: 'annotations', column: 'type' },
    ],
  },
];

// Flat view of every field, for iteration by later phases.
export const FIELDS: Field[] = GROUPS.flatMap((g) => g.fields);

// Project -> the only data_source it can have (ADR-0003). synapse data is never
// simulation-derived, so the filter panel (and the forms) disable the opposing
// simulation arm when synapse is selected. Mirrored from filter_fields.py.
export const PROJECT_REQUIRES_DATA_SOURCE: Record<
  string,
  'experimental' | 'simulation'
> = { synapse: 'experimental' };
