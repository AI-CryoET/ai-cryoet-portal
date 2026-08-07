// Builders that turn a sample/acquisition entity into the ordered list of
// metadata sections rendered inside MetadataDrawer. Each builder returns the
// full field list; MetadataSection drops empty rows and empty sections, so the
// builders don't need to guard individual optional values.

import type { AcquisitionOut, SampleDetail } from '~/types';
import type { MetadataRow, MetadataSectionData } from './MetadataSection';

function num(value: number | null | undefined, unit?: string): string | null {
  if (value == null) {
    return null;
  }
  return unit ? `${value} ${unit}` : `${value}`;
}

function numList(value: number[] | null | undefined): string | null {
  if (!value || value.length === 0) {
    return null;
  }
  return value.join(', ');
}

// Per-image MDOC arrays (dose / defocus per tilt) are too long to dump into a
// table cell, so they're surfaced as a "min–max unit" span instead.
function numRange(
  value: number[] | null | undefined,
  unit?: string
): string | null {
  if (!value || value.length === 0) {
    return null;
  }
  const lo = Math.min(...value);
  const hi = Math.max(...value);
  const span = lo === hi ? `${lo}` : `${lo} – ${hi}`;
  return unit ? `${span} ${unit}` : span;
}

function bool(value: boolean | null | undefined): string | null {
  if (value == null) {
    return null;
  }
  return value ? 'Yes' : 'No';
}

// Sections describing the sample itself (also reused on the acquisition drawer,
// since every acquisition within a sample shares this metadata).
export function sampleMetadataSections(
  sample: SampleDetail
): MetadataSectionData[] {
  const sections: MetadataSectionData[] = [];

  sections.push({
    title: 'Sample Overview',
    defaultExpanded: true,
    rows: [
      { label: 'Sample ID', value: sample.sample_id },
      { label: 'Project', value: sample.project },
      { label: 'Lab', value: sample.lab_name },
      { label: 'Data source', value: sample.data_source },
      { label: 'Type', value: sample.type },
      { label: 'Cell type', value: sample.cell_type },
      { label: 'Description', value: sample.description }
    ]
  });

  // Which sections apply is driven by the sample's project / data source, not
  // by whether the sub-entity happens to be populated — so an applicable
  // section still renders (with placeholder values) when its data is missing.
  const isChromatin = sample.project === 'chromatin';
  const isExperimental = sample.data_source === 'experimental';
  const isSimulation = sample.data_source === 'simulation';

  if (isChromatin) {
    const c = sample.chromatin;
    sections.push({
      title: 'Chromatin',
      rows: [
        { label: 'Substrate', value: c?.substrate },
        { label: 'Buffer', value: c?.buffer },
        { label: 'Linker length', value: num(c?.linker_length_bp, 'bp') },
        { label: 'Linker pattern', value: numList(c?.linker_pattern) },
        { label: 'Linker distribution', value: c?.linker_distribution },
        {
          label: 'Linker length fraction',
          value: num(c?.linker_length_fraction)
        },
        { label: 'PTM', value: c?.ptm },
        { label: 'Histone variants', value: c?.histone_variants },
        { label: 'Transcription factors', value: c?.transcription_factors },
        { label: 'Nucleosome count', value: num(c?.nucleosome_count) },
        {
          label: 'Nucleosome concentration',
          value: num(c?.nucleosome_uM, 'µM')
        },
        {
          label: 'Nucleosome footprint',
          value: numList(c?.nucleosome_footprint)
        },
        { label: 'DNA length', value: num(c?.dna_length_bp, 'bp') },
        { label: 'Sequence identity', value: c?.sequence_identity }
      ]
    });
  }

  if (isExperimental) {
    const fr = sample.freezing;
    sections.push({
      title: 'Freezing',
      rows: [
        { label: 'Method', value: fr?.method },
        { label: 'Grid type', value: fr?.grid_type },
        { label: 'Solution type', value: fr?.solution_type },
        { label: 'Cryoprotectant', value: fr?.cryoprotectant },
        { label: 'Planchette size', value: fr?.planchette_size },
        { label: 'Spacer thickness', value: fr?.spacer_thickness }
      ]
    });

    const m = sample.milling;
    sections.push({
      title: 'Milling',
      rows: [
        { label: 'Scheme', value: m?.scheme },
        { label: 'Quality', value: m?.quality },
        { label: 'Date', value: m?.date }
      ]
    });

    // One section per label; when none are recorded, still show an empty
    // "Label" section so the field set is visible.
    const labels = sample.label.length > 0 ? sample.label : [null];
    labels.forEach((l, i) => {
      const size = Array.isArray(l?.aunp_size_nm)
        ? l.aunp_size_nm.join(', ')
        : l?.aunp_size_nm;
      sections.push({
        title: labels.length > 1 ? `Label ${l?.ordinal ?? i + 1}` : 'Label',
        rows: [
          { label: 'Target', value: l?.label_target },
          { label: 'AuNP type', value: l?.aunp_type },
          { label: 'AuNP size', value: size != null ? `${size} nm` : null },
          { label: 'Conjugation', value: l?.conjugation },
          { label: 'Conjugation target', value: l?.conjugation_target },
          { label: 'Fluorophore', value: l?.fluorophore },
          { label: 'Notes', value: l?.notes }
        ]
      });
    });

    const f = sample.fiducial;
    const concentration =
      f?.concentration_value != null
        ? `${f.concentration_value}${f.concentration_unit ? ` ${f.concentration_unit}` : ''}`
        : null;
    sections.push({
      title: 'Fiducial Markers',
      rows: [
        { label: 'AuNP size', value: num(f?.aunp_size_nm, 'nm') },
        { label: 'Product name', value: f?.product_name },
        { label: 'Vendor', value: f?.vendor },
        { label: 'Catalog number', value: f?.catalog_number },
        { label: 'Concentration', value: concentration }
      ]
    });
  }

  if (isSimulation) {
    sections.push({
      title: 'Simulation',
      rows: [{ label: 'Dataset type', value: sample.simulation?.dataset_type }]
    });

    // One section (table) per MD run; when none are recorded, still show an
    // empty "MD run" section so the field set is visible.
    const runs = sample.md_run.length > 0 ? sample.md_run : [null];
    runs.forEach(r => {
      sections.push({
        title: r ? `MD run: ${r.md_run_id}` : 'MD run',
        rows: [
          { label: 'Seed', value: num(r?.seed) },
          { label: 'Computer', value: r?.computer },
          { label: 'Sample time', value: num(r?.sample_time) },
          { label: 'Timestep', value: num(r?.timestep) },
          { label: 'Force field version', value: r?.force_field_version },
          { label: 'Reference contact', value: r?.reference_contact }
        ]
      });
    });
  }

  return sections;
}

// Sections describing a single acquisition. The shared sample sections are
// appended by the acquisition route so the drawer mirrors the reference layout.
export function acquisitionMetadataSections(
  acq: AcquisitionOut
): MetadataSectionData[] {
  const sections: MetadataSectionData[] = [];

  sections.push({
    title: 'Acquisition Overview',
    defaultExpanded: true,
    rows: [
      { label: 'Acquisition ID', value: acq.acquisition_id },
      { label: 'Facility', value: acq.facility },
      { label: 'Resolution', value: num(acq.resolution, 'Å') },
      {
        label: 'Acquisition quality',
        value:
          acq.acquisition_quality != null
            ? `${acq.acquisition_quality} / 5`
            : null
      },
      { label: 'Date collected', value: acq.date_collected },
      { label: 'Frame count', value: num(acq.frame_count) }
    ]
  });

  sections.push({
    title: 'Microscope & Imaging',
    rows: [
      { label: 'Microscope', value: acq.microscope },
      { label: 'Camera', value: acq.camera },
      { label: 'Voltage', value: num(acq.voltage, 'kV') },
      { label: 'Pixel size', value: num(acq.pixel_size, 'Å') },
      { label: 'Energy filter', value: acq.energy_filter },
      {
        label: 'Energy filter slit width',
        value: num(acq.energy_filter_slit_width, 'eV')
      },
      { label: 'Phase plate', value: bool(acq.phase_plate) }
    ]
  });

  // Acquisition-level tilt geometry + dose. The MDOC describes the acquisition's
  // tilt scheme (shared by all its tilt series), so it lives here rather than
  // per–tilt-series. Tilt range prefers the MDOC tilt_min/tilt_max, falling back
  // to the bounds of the full per-image angle list. Per-image arrays (dose /
  // defocus per tilt) are shown as ranges rather than full dumps.
  const angles = acq.tilt_angles;
  const hasAngles = !!angles && angles.length > 0;
  const tiltMin = acq.tilt_min ?? (hasAngles ? Math.min(...angles!) : null);
  const tiltMax = acq.tilt_max ?? (hasAngles ? Math.max(...angles!) : null);
  sections.push({
    title: 'Tilt Geometry & Dose',
    rows: [
      { label: 'Tilt count', value: hasAngles ? `${angles!.length}` : null },
      {
        label: 'Tilt range',
        value:
          tiltMin != null && tiltMax != null
            ? `${tiltMin}° to ${tiltMax}°`
            : null
      },
      { label: 'Tilt spacing', value: num(acq.tilt_spacing, '°') },
      { label: 'Tilt axis', value: num(acq.tilt_axis, '°') },
      { label: 'Total dose', value: num(acq.total_dose, 'e/Å²') },
      { label: 'Dose per tilt', value: numRange(acq.dose_per_tilt, 'e/Å²') },
      { label: 'Defocus range (target)', value: acq.defocus_range },
      {
        label: 'Defocus per image',
        value: numRange(acq.defocus_per_image, 'µm')
      }
    ]
  });

  // One accordion per tilt series, titled "Tilt series: {id}" (mirrors the
  // sample drawer's per-label sections). Acquisition-level tilt geometry lives
  // in the section above; these list each authored series' alignment provenance.
  // When none are recorded, still show an empty "Tilt series" section so the
  // field set stays visible.
  const tiltSeriesList = acq.tilt_series.length > 0 ? acq.tilt_series : [null];
  tiltSeriesList.forEach(ts => {
    sections.push({
      title: ts ? `Tilt series: ${ts.tilt_series_id}` : 'Tilt series',
      rows: [
        { label: 'Tilt series ID', value: ts?.tilt_series_id },
        { label: 'Derived from', value: ts?.derived_from },
        { label: 'Aligned', value: bool(ts?.is_aligned) },
        { label: 'Alignment software', value: ts?.alignment_software },
        { label: 'Alignment method', value: ts?.alignment_method }
      ]
    });
  });

  const tomoRows: MetadataRow[] = [];
  const totalTomos =
    acq.raw_tomograms.length + acq.post_processed_tomograms.length;
  tomoRows.push({ label: 'Total tomograms', value: `${totalTomos}` });
  acq.raw_tomograms.forEach(t => {
    const prefix =
      acq.raw_tomograms.length > 1 ? `Raw (${t.tomogram_id}) ` : 'Raw ';
    const dims =
      t.image_size_x != null && t.image_size_y != null && t.image_size_z != null
        ? `${t.image_size_x} × ${t.image_size_y} × ${t.image_size_z}`
        : null;
    tomoRows.push({
      label: `${prefix}voxel size`,
      value: num(t.voxel_size, 'Å')
    });
    tomoRows.push({ label: `${prefix}dimensions`, value: dims });
    tomoRows.push({ label: `${prefix}pipeline`, value: t.pipeline });
    tomoRows.push({ label: `${prefix}software`, value: t.software });
  });
  tomoRows.push({
    label: 'Post-processed tomograms',
    value: acq.post_processed_tomograms.length
      ? `${acq.post_processed_tomograms.length}`
      : null
  });
  tomoRows.push({
    label: 'Annotations',
    value: acq.annotations.length ? `${acq.annotations.length}` : null
  });
  sections.push({ title: 'Tomograms Summary', rows: tomoRows });

  if (
    acq.md_source &&
    (acq.md_source.md_run_id || acq.md_source.frame != null)
  ) {
    sections.push({
      title: 'MD Source',
      rows: [
        { label: 'MD run ID', value: acq.md_source.md_run_id },
        { label: 'Frame', value: num(acq.md_source.frame) }
      ]
    });
  }

  return sections;
}
