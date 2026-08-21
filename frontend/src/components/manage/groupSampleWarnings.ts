import type { IssueGroup, IssueSeverity } from '~/types';

const SEVERITY_RANK: Record<IssueSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2
};

// Which data level a single message applies to — drives the Ⓢ/Ⓐ/Ⓡ icon and
// the top-to-bottom ordering (sample, then acquisition, then reconstruction).
export type MessageScope = 'sample' | 'acquisition' | 'reconstruction';

export interface WarningMessage {
  text: string;
  scope: MessageScope;
}

// "Still present as of" / "Resolved at" inputs for one leaf. Rolled up across
// the underlying issue groups the leaf came from (min still-present, worst
// re-evaluated, max resolved) — same rules the old per-row rollup used.
interface Meta {
  reEvaluated: boolean;
  stillPresentAt: number;
  resolved_at: number | null;
}

export interface AffectedReconstruction extends Meta {
  reconstruction_alignment_id: string;
  acquisition_id: string;
  messages: WarningMessage[];
}

export interface AffectedAcquisition extends Meta {
  acquisition_id: string;
  acquisition_path: string | null;
  file_kind: string;
  // This acquisition's own (acquisition-scoped) messages. Reconstruction-owned
  // messages live on the reconstruction below, not here.
  messages: WarningMessage[];
  reconstructions: AffectedReconstruction[];
}

// A sample-level leaf: either the sample.toml's own messages (md_run_id null —
// its edit/copy actions live on the band header) or one md_run's messages
// (md_run_id set — rendered as a pseudo-entity in the Acquisition column so its
// md_run authoring link survives).
export interface SampleLevelEntry extends Meta {
  md_run_id: string | null;
  file_kind: string;
  messages: WarningMessage[];
}

// One sample = one band (the driving organizational element). All of a sample's
// warnings across categories, file kinds, acquisitions and reconstructions
// collapse into a single band.
export interface SampleBand {
  key: string;
  sample_id: string | null;
  sample_path: string | null;
  // file_kind for the header edit link (sample_toml when a sample.toml message
  // is present, so the header edit icon opens the sample authoring tab).
  file_kind: string;
  severity: IssueSeverity;
  // A sample.toml sample-scoped message exists → the band header shows the
  // copy-path + edit-metadata actions for the sample itself.
  hasSampleEdit: boolean;
  sampleEntries: SampleLevelEntry[];
  acquisitions: AffectedAcquisition[];
}

function metaOf(g: IssueGroup): Meta {
  const reEvaluated =
    g.latest_run_id != null && g.last_seen_run_id === g.latest_run_id;
  return {
    reEvaluated,
    stillPresentAt: reEvaluated
      ? (g.latest_scan_at ?? g.last_seen_at)
      : g.last_seen_at,
    resolved_at: g.resolved_at
  };
}

// Fold a group's meta into a leaf: keep the oldest still-present, fail
// re-evaluated if any owner was skipped, keep the newest resolved.
function mergeMeta(target: Meta, m: Meta): void {
  if (!m.reEvaluated) {
    target.reEvaluated = false;
  }
  target.stillPresentAt = Math.min(target.stillPresentAt, m.stillPresentAt);
  if (
    m.resolved_at != null &&
    (target.resolved_at == null || m.resolved_at > target.resolved_at)
  ) {
    target.resolved_at = m.resolved_at;
  }
}

function newMeta(): Meta {
  return {
    reEvaluated: true,
    stillPresentAt: Number.MAX_SAFE_INTEGER,
    resolved_at: null
  };
}

// Regroups the flat (entity, file_kind) `IssueGroup[]` the API returns into one
// band per sample, merging every category/file_kind/acquisition/reconstruction
// under it. `IssueItem.reconstruction_alignment_id` decides reconstruction
// scope; a group with an `acquisition_id` but no recon id is acquisition scope;
// everything else is sample scope (sample.toml or md_run).
export function groupBySample(groups: IssueGroup[]): SampleBand[] {
  const bands = new Map<string, SampleBand>();

  for (const g of groups) {
    const m = metaOf(g);
    const bandKey = g.sample_id ?? '__run__';
    let band = bands.get(bandKey);
    if (!band) {
      band = {
        key: bandKey,
        sample_id: g.sample_id,
        sample_path: g.sample_path,
        file_kind: g.file_kind,
        severity: g.severity,
        hasSampleEdit: false,
        sampleEntries: [],
        acquisitions: []
      };
      bands.set(bandKey, band);
    }
    if (SEVERITY_RANK[g.severity] < SEVERITY_RANK[band.severity]) {
      band.severity = g.severity;
    }
    if (g.sample_path && !band.sample_path) {
      band.sample_path = g.sample_path;
    }

    for (const issue of g.issues) {
      if (g.acquisition_id != null) {
        let acq = band.acquisitions.find(
          a => a.acquisition_id === g.acquisition_id
        );
        if (!acq) {
          acq = {
            acquisition_id: g.acquisition_id,
            acquisition_path: g.acquisition_path,
            file_kind: g.file_kind,
            messages: [],
            reconstructions: [],
            ...newMeta()
          };
          band.acquisitions.push(acq);
        }
        if (issue.reconstruction_alignment_id != null) {
          const reconId = issue.reconstruction_alignment_id;
          let recon = acq.reconstructions.find(
            r => r.reconstruction_alignment_id === reconId
          );
          if (!recon) {
            recon = {
              reconstruction_alignment_id: reconId,
              acquisition_id: g.acquisition_id,
              messages: [],
              ...newMeta()
            };
            acq.reconstructions.push(recon);
          }
          mergeMeta(recon, m);
          recon.messages.push({ text: issue.message, scope: 'reconstruction' });
        } else {
          mergeMeta(acq, m);
          acq.messages.push({ text: issue.message, scope: 'acquisition' });
        }
      } else {
        // Sample-level: sample.toml and any other non-md_run sample-scoped
        // kinds collapse into one entry (actions on the header); each md_run
        // gets its own entry (a pseudo-entity so its authoring link survives).
        const mdRunId = g.file_kind === 'md_run_toml' ? g.md_run_id : null;
        let entry = band.sampleEntries.find(e => e.md_run_id === mdRunId);
        if (!entry) {
          entry = {
            md_run_id: mdRunId,
            file_kind: g.file_kind,
            messages: [],
            ...newMeta()
          };
          band.sampleEntries.push(entry);
        }
        mergeMeta(entry, m);
        entry.messages.push({ text: issue.message, scope: 'sample' });
        if (g.file_kind === 'sample_toml') {
          band.hasSampleEdit = true;
          band.file_kind = 'sample_toml';
        }
      }
    }
  }

  const out = Array.from(bands.values());
  for (const band of out) {
    band.acquisitions.sort((a, b) =>
      a.acquisition_id.localeCompare(b.acquisition_id)
    );
    for (const acq of band.acquisitions) {
      acq.reconstructions.sort((a, b) =>
        a.reconstruction_alignment_id.localeCompare(
          b.reconstruction_alignment_id
        )
      );
    }
  }
  // Errors first, then warnings/info; run-level band (null sample_id) last.
  out.sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      (a.sample_id ?? '￿').localeCompare(b.sample_id ?? '￿')
  );
  return out;
}

// One flattened line of a band's inner table. Sample-scoped rows come first,
// then acquisition-scoped, then reconstruction rows nested under their
// acquisition. A multi-row acquisition (its own message plus/or several
// reconstructions) shows its name only once and shades every row of the group
// so they read as one acquisition — no repeated name, no dash.
export interface WarningInnerRow {
  id: string;
  acq: AffectedAcquisition | null;
  recon: AffectedReconstruction | null;
  mdRunId: string | null;
  // Show the acquisition name/actions on this row (first row of its group).
  showAcqLabel: boolean;
  // The acquisition owns a message of its own → its name gets copy/edit
  // actions. False when the name is only a group header for reconstructions.
  acqActions: boolean;
  // Alternates per acquisition (including all its reconstruction rows) so
  // consecutive acquisitions read as distinct bands, regardless of how many
  // rows each one spans.
  shaded: boolean;
  messages: WarningMessage[];
  reEvaluated: boolean;
  stillPresentAt: number;
  resolved_at: number | null;
}

export function flattenBand(band: SampleBand): WarningInnerRow[] {
  const out: WarningInnerRow[] = [];

  // 1. sample.toml messages (actions live on the band header → no acq label).
  // 2. md_run messages (rendered as a pseudo-entity in the Acquisition column).
  for (const entry of band.sampleEntries) {
    if (entry.messages.length === 0) {
      continue;
    }
    out.push({
      id: entry.md_run_id ? `mdrun:${entry.md_run_id}` : 'sample',
      acq: null,
      recon: null,
      mdRunId: entry.md_run_id,
      showAcqLabel: entry.md_run_id != null,
      acqActions: entry.md_run_id != null,
      shaded: false,
      messages: entry.messages,
      reEvaluated: entry.reEvaluated,
      stillPresentAt: entry.stillPresentAt,
      resolved_at: entry.resolved_at
    });
  }

  // 3. acquisitions: an acquisition-scoped row (if any) then its
  //    reconstruction rows. A multi-row group shows the name once; every
  //    row in the group shares one shade, alternating acquisition to
  //    acquisition.
  let acqIndex = 0;
  for (const acq of band.acquisitions) {
    const recons = acq.reconstructions.filter(r => r.messages.length > 0);
    const hasAcqMsg = acq.messages.length > 0;
    const groupSize = (hasAcqMsg ? 1 : 0) + recons.length;
    if (groupSize === 0) {
      continue;
    }
    const shaded = acqIndex % 2 === 1;
    acqIndex++;
    let first = true;

    if (hasAcqMsg) {
      out.push({
        id: `acq:${acq.acquisition_id}`,
        acq,
        recon: null,
        mdRunId: null,
        showAcqLabel: true,
        acqActions: true,
        shaded,
        messages: acq.messages,
        reEvaluated: acq.reEvaluated,
        stillPresentAt: acq.stillPresentAt,
        resolved_at: acq.resolved_at
      });
      first = false;
    }

    for (const recon of recons) {
      out.push({
        id: `acq:${acq.acquisition_id}/recon:${recon.reconstruction_alignment_id}`,
        acq,
        recon,
        mdRunId: null,
        showAcqLabel: first,
        // The acquisition name here is only a group header — the message
        // belongs to the reconstruction, so the acquisition gets no actions.
        acqActions: false,
        shaded,
        messages: recon.messages,
        reEvaluated: recon.reEvaluated,
        stillPresentAt: recon.stillPresentAt,
        resolved_at: recon.resolved_at
      });
      first = false;
    }
  }

  return out;
}
