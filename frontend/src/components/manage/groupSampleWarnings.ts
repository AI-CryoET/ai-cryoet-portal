import type { IssueGroup, IssueScope, IssueSeverity } from '~/types';

const SEVERITY_RANK: Record<IssueSeverity, number> = {
  error: 0,
  warning: 1,
  info: 2
};

// One acquisition affected by a sample+category warning row. `messages`
// holds this acquisition's own issue text(s) for the category (usually one)
// — shown on hover when it differs from the row's representative message,
// since filenames/ids embedded in the message can vary per acquisition.
export interface AffectedAcquisition {
  acquisition_id: string;
  acquisition_path: string | null;
  file_kind: string;
  messages: string[];
}

// One row of the regrouped warnings table: a sample + warning category
// (+ md_run_id, for md_run-scoped issues, which aren't acquisitions and
// aren't merged across runs). `acquisitions` is empty when the issue is
// sample-level only (or run-scoped) — the UI renders a dash for those.
export interface SampleWarningRow {
  key: string;
  scope: IssueScope;
  sample_id: string | null;
  sample_path: string | null;
  md_run_id: string | null;
  file_kind: string;
  category: string;
  severity: IssueSeverity;
  message: string;
  acquisitions: AffectedAcquisition[];
  first_seen_at: number;
  // "Still present as of" rollup: true when every underlying group was
  // re-evaluated in the latest completed scan; false means at least one
  // owner was skipped, and `stillPresentAt` is the oldest such check.
  reEvaluated: boolean;
  stillPresentAt: number;
  // Max `resolved_at` across merged groups — only meaningful for the
  // recently-resolved table; null on the outstanding-issues table.
  resolved_at: number | null;
}

function rowKey(g: IssueGroup, category: string): string {
  return [g.sample_id ?? '', g.file_kind, category, g.md_run_id ?? ''].join(
    '|'
  );
}

// Regroups the flat (entity, file_kind) `IssueGroup[]` the API returns into
// one row per (sample, file_kind, category, md_run_id) — collapsing the same
// warning type across every acquisition it affects, per the manage-warnings
// redesign. `IssueItem.category` is the stable, filename-free part of a
// warning; `message` is free text that often embeds a specific file/folder
// name, so it stays per-acquisition rather than becoming the row's label.
export function groupSampleWarnings(groups: IssueGroup[]): SampleWarningRow[] {
  const rows = new Map<string, SampleWarningRow>();

  for (const g of groups) {
    const reEvaluated =
      g.latest_run_id != null && g.last_seen_run_id === g.latest_run_id;
    const stillPresentAt = reEvaluated
      ? (g.latest_scan_at ?? g.last_seen_at)
      : g.last_seen_at;

    for (const issue of g.issues) {
      const key = rowKey(g, issue.category);
      let row = rows.get(key);
      if (!row) {
        row = {
          key,
          scope: g.scope,
          sample_id: g.sample_id,
          sample_path: g.sample_path,
          md_run_id: g.md_run_id,
          file_kind: g.file_kind,
          category: issue.category,
          severity: g.severity,
          message: issue.message,
          acquisitions: [],
          first_seen_at: g.first_seen_at,
          reEvaluated,
          stillPresentAt,
          resolved_at: g.resolved_at
        };
        rows.set(key, row);
      } else {
        if (SEVERITY_RANK[g.severity] < SEVERITY_RANK[row.severity]) {
          row.severity = g.severity;
        }
        if (g.first_seen_at < row.first_seen_at) {
          row.first_seen_at = g.first_seen_at;
        }
        if (!reEvaluated) {
          row.reEvaluated = false;
          row.stillPresentAt = Math.min(row.stillPresentAt, stillPresentAt);
        }
        if (
          g.resolved_at != null &&
          (row.resolved_at == null || g.resolved_at > row.resolved_at)
        ) {
          row.resolved_at = g.resolved_at;
        }
      }

      if (g.acquisition_id != null) {
        let acq = row.acquisitions.find(
          a => a.acquisition_id === g.acquisition_id
        );
        if (!acq) {
          acq = {
            acquisition_id: g.acquisition_id,
            acquisition_path: g.acquisition_path,
            file_kind: g.file_kind,
            messages: []
          };
          row.acquisitions.push(acq);
        }
        acq.messages.push(issue.message);
      }
    }
  }

  const out = Array.from(rows.values());
  for (const row of out) {
    row.acquisitions.sort((a, b) =>
      a.acquisition_id.localeCompare(b.acquisition_id)
    );
    // Representative message: the alphabetically-first affected acquisition,
    // deterministic across re-fetches. Sample/run-scoped rows (no
    // acquisitions) keep whichever message was first seen.
    if (row.acquisitions.length > 0) {
      row.message = row.acquisitions[0].messages[0];
    }
  }
  out.sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      (a.sample_id ?? '').localeCompare(b.sample_id ?? '')
  );
  return out;
}
