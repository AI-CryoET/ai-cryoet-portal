// PROTOTYPE — throwaway. Hand-stubbed representative subset of docs/schema.md,
// enough to judge the two layout variants (nesting, authored/derived badges,
// arm/project gating). The real page will generate this from docs/schema.md
// once a layout is chosen. Delete this file when folding the winner in.

export type SourceKind = 'authored' | 'derived'
export type Arm = 'experimental' | 'simulation'

export interface SchemaField {
  field: string
  type: string
  source: string // human label: 'sample.toml [sample]', 'MDOC', 'directory', …
  kind: SourceKind
  notes?: string
}

export interface SchemaEntity {
  id: string
  name: string
  cardinality: string // 'one per sample', '0..N per acquisition', …
  arm?: Arm // gating: only shows in this arm; undefined = both
  chromatinOnly?: boolean // gating: only when project = chromatin
  fields: SchemaField[]
  children?: SchemaEntity[]
}

const A = (
  field: string,
  type: string,
  source: string,
  notes?: string,
): SchemaField => ({ field, type, source, kind: 'authored', notes })

const D = (
  field: string,
  type: string,
  source: string,
  notes?: string,
): SchemaField => ({ field, type, source, kind: 'derived', notes })

export const SCHEMA: SchemaEntity[] = [
  {
    id: 'sample',
    name: 'Sample',
    cardinality: 'one per sample',
    fields: [
      D('sample_id', 'text (PK)', 'directory', 'Sample folder name.'),
      A('lab_name', 'enum', 'sample.toml [sample]', 'collepardo, gouaux, rosen, villa'),
      D('data_source', 'enum', 'directory', 'experimental or simulation, from the top-level arm.'),
      A('project', 'enum', 'sample.toml [sample]', 'chromatin, synapse, or nanogold.'),
      A('type', 'text', 'sample.toml [sample]', 'e.g. cellular / reconstituted.'),
      A('cell_type', 'text', 'sample.toml [sample]', 'Required when type = cellular.'),
      A('description', 'text', 'sample.toml [sample]', 'Free text.'),
      D('path', 'text', 'directory', 'Absolute sample-directory path.'),
    ],
    children: [
      {
        id: 'chromatin',
        name: 'Chromatin',
        cardinality: 'one per sample',
        chromatinOnly: true,
        fields: [
          A('substrate', 'text', 'sample.toml [chromatin]', 'synthetic / native / n/a.'),
          A('linker_length_bp', 'float', 'sample.toml [chromatin]', 'Homogenous linker length.'),
          A('linker_pattern', 'list[int]', 'sample.toml [chromatin]', 'Patterned linker lengths.'),
          A('buffer', 'text', 'sample.toml [chromatin]', 'Species + conc + additives.'),
          A('ptm', 'text', 'sample.toml [chromatin]'),
          A('nucleosome_count', 'integer', 'sample.toml [chromatin]'),
          A('dna_length_bp', 'integer', 'sample.toml [chromatin]'),
          D('linker_length_fraction', 'float', 'derived', 'Computed on ingest.'),
        ],
      },
      {
        id: 'label',
        name: 'Gold-nanoparticle label',
        cardinality: '0..N per sample',
        arm: 'experimental',
        fields: [
          A('label_target', 'text', 'sample.toml [label]'),
          A('aunp_type', 'text', 'sample.toml [label]', 'monomer, dimer, …'),
          A('aunp_size_nm', 'float | list', 'sample.toml [label]'),
          A('conjugation', 'text', 'sample.toml [label]', 'Fab / nanobody / chemical_tag / none.'),
          A('conjugation_target', 'text', 'sample.toml [label]', 'e.g. GluA2.'),
        ],
      },
      {
        id: 'fiducial',
        name: 'Fiducial AuNP',
        cardinality: 'one per sample',
        arm: 'experimental',
        fields: [
          A('aunp_size_nm', 'float | list', 'sample.toml [fiducial]'),
          A('vendor', 'text', 'sample.toml [fiducial]'),
          A('catalog_number', 'text', 'sample.toml [fiducial]'),
          A('concentration_value', 'float', 'sample.toml [fiducial]'),
          A('concentration_unit', 'text', 'sample.toml [fiducial]'),
        ],
      },
      {
        id: 'freezing',
        name: 'Freezing / grid prep',
        cardinality: 'one per sample',
        arm: 'experimental',
        fields: [
          A('grid_type', 'text', 'sample.toml [freezing]'),
          A('solution_type', 'text', 'sample.toml [freezing]'),
          A('cryoprotectant', 'text', 'sample.toml [freezing]'),
          A('method', 'text', 'sample.toml [freezing]', 'plunge_frozen / HPF.'),
          A('planchette_size', 'text', 'sample.toml [freezing]', 'HPF only.'),
        ],
      },
      {
        id: 'milling',
        name: 'Milling',
        cardinality: 'one per sample',
        arm: 'experimental',
        fields: [
          A('scheme', 'text', 'sample.toml [milling]'),
          A('date', 'date', 'sample.toml [milling]', 'YYYY-MM-DD.'),
          A('quality', 'text', 'sample.toml [milling]'),
        ],
      },
      {
        id: 'simulation',
        name: 'Simulation',
        cardinality: 'one per sample',
        arm: 'simulation',
        fields: [
          D('dataset_type', 'enum', 'directory', 'bulk / single_molecule / slab, from the MdSimulation subdir.'),
        ],
      },
      {
        id: 'md_run',
        name: 'MD run',
        cardinality: '0..N per sample',
        arm: 'simulation',
        fields: [
          D('md_run_id', 'text (PK)', 'directory', 'Run folder name under MdRuns/.'),
          A('seed', 'integer', 'md_run.toml', 'RNG seed for the run.'),
          A('sample_time', 'float', 'md_run.toml', 'Total simulated time.'),
          A('timestep', 'float', 'md_run.toml', 'Integration timestep.'),
          A('computer', 'text', 'md_run.toml'),
          A('force_field_version', 'text', 'md_run.toml'),
        ],
      },
    ],
  },
  {
    id: 'acquisition',
    name: 'Acquisition',
    cardinality: 'one per imaging position',
    fields: [
      D('acquisition_id', 'text (PK)', 'directory', 'Acquisition folder name, e.g. Position_86.'),
      D('sample_id', 'text (FK)', 'directory', 'Parent sample directory name.'),
      A('resolution', 'float', 'acquisition.toml [acquisition]', 'Å. Nominal target.'),
      A('tilt_spacing', 'float', 'acquisition.toml [acquisition]', 'Target tilt step (intent).'),
      A('defocus_range', 'text', 'acquisition.toml [acquisition]', 'µm, free text (intent).'),
      A('microscope', 'text', 'acquisition.toml [acquisition]', 'Model name.'),
      A('acquisition_quality', 'integer', 'acquisition.toml [acquisition]', '1–5 rubric.'),
      D('pixel_size', 'float', 'MDOC', 'Å.'),
      D('total_dose', 'float', 'MDOC', 'e/Å², summed.'),
      D('tilt_min', 'float', 'MDOC', 'Degrees.'),
      D('tilt_max', 'float', 'MDOC', 'Degrees.'),
      D('tilt_axis', 'float', 'MDOC', 'Degrees.'),
      D('tilt_angles', 'list[float]', 'MDOC', 'Full per-image tilt-angle list; powers the polar plot.'),
      D('date_collected', 'date', 'MDOC'),
      D('voltage', 'float', 'MDOC', 'kV.'),
      D('camera', 'text', '.eer / .tiff', '.eer → Falcon; .tiff → K3.'),
      D('frame_count', 'integer', 'MDOC', 'Number of tilts.'),
      D('path', 'text', 'directory', 'Absolute acquisition-directory path.'),
    ],
    children: [
      {
        id: 'tilt_series',
        name: 'Tilt series',
        cardinality: '0..N per acquisition',
        fields: [
          A('tilt_series_id', 'text (PK)', 'acquisition.toml [[tilt_series]].id', 'Must match the folder under TiltSeries/.'),
          A('derived_from', 'text', 'acquisition.toml [[tilt_series]]', '"Frames" or another tilt_series_id.'),
          A('is_aligned', 'boolean', 'acquisition.toml [[tilt_series]]'),
          A('alignment_software', 'text', 'acquisition.toml [[tilt_series]]', 'e.g. IMOD, AreTomo3.'),
          A('alignment_method', 'text', 'acquisition.toml [[tilt_series]]', 'fiducial / patch_tracking / …'),
          D('st_path', 'text', 'directory', 'Path to the stacked .mrc.'),
          D('alignment_files', 'list[text]', 'directory', 'Artifacts under alignment/.'),
        ],
      },
      {
        id: 'md_source',
        name: 'MD source',
        cardinality: 'one per acquisition',
        arm: 'simulation',
        fields: [
          A('md_run_id', 'text (FK)', 'acquisition.toml [md_source]', 'Should match an MdRuns/{id}/ folder.'),
          A('frame', 'integer', 'acquisition.toml [md_source]', 'Frame index within the MD run.'),
        ],
      },
      {
        id: 'raw_tomogram',
        name: 'Raw tomogram',
        cardinality: 'one per acquisition (optional)',
        fields: [
          A('tomogram_id', 'text (PK)', 'acquisition.toml [raw_tomogram].id', 'Must match the processing folder name.'),
          A('pipeline', 'text', 'acquisition.toml [raw_tomogram]', 'Human description.'),
          A('software', 'text', 'acquisition.toml [raw_tomogram]'),
          D('voxel_size', 'float', 'MRC header', 'Å/pixel.'),
          A('derived_from', 'list[text]', 'acquisition.toml [raw_tomogram]', 'Empty for raw reconstructions.'),
          D('image_size_z', 'integer', 'MRC header'),
          D('mrc_path', 'text', 'directory'),
          D('zarr_axes', 'text', 'OME-Zarr .zattrs', 'Axis order.'),
        ],
      },
      {
        id: 'post_processed_tomogram',
        name: 'Post-processed tomogram',
        cardinality: '0..N per acquisition',
        fields: [
          A('tomogram_id', 'text (PK)', 'acquisition.toml [[post_processed_tomogram]].id'),
          A('denoising_software', 'text', 'acquisition.toml [[post_processed_tomogram]]'),
          A('ctf_software', 'text', 'acquisition.toml [[post_processed_tomogram]]'),
          D('voxel_size', 'float', 'MRC header', 'Å/pixel.'),
          A('derived_from', 'list[text]', 'acquisition.toml [[post_processed_tomogram]]', 'Lineage.'),
          D('image_size_z', 'integer', 'MRC header'),
          D('mrc_path', 'text', 'directory'),
          D('size_bytes', 'integer', 'filesystem', 'On-disk size via os.stat.'),
        ],
      },
      {
        id: 'annotation',
        name: 'Annotation',
        cardinality: '0..N per acquisition',
        fields: [
          A('annotation_id', 'text (PK)', 'acquisition.toml [[annotation]].id', 'e.g. membrain_seg_v10.'),
          A('type', 'text', 'acquisition.toml [[annotation]]', 'membrane_segmentation, sta_result, …'),
          A('target_tomogram', 'text (FK)', 'acquisition.toml [[annotation]]', 'Tomogram this was generated from.'),
          D('files', 'list[text]', 'directory', '.star / .mrc / .ome.zarr / .png artifacts.'),
        ],
      },
    ],
  },
]
