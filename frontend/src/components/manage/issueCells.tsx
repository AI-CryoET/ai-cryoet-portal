import { Chip, Stack, Tooltip, Typography } from '@mui/material';
import EditNoteIcon from '@mui/icons-material/EditNote';
import { CustomLink, IconButtonLink } from '~/components/CustomLink';
import { CopyIconButton } from '~/components/common/CopyIconButton';
import type { IssueGroup } from '~/types';
import type { AffectedAcquisition } from './groupSampleWarnings';

// Issue timestamps are Unix seconds; render in the viewer's locale.
export function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

// First-seen wants a date-only reading (matches the wireframe's "2026-06-18").
export function formatDate(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleDateString();
}

const SEVERITY_COLOR = {
  error: 'error',
  warning: 'warning',
  info: 'info'
} as const;

export function SeverityPill({
  severity
}: {
  readonly severity: IssueGroup['severity'];
}) {
  return (
    <Chip
      color={SEVERITY_COLOR[severity]}
      label={severity}
      size="small"
      variant="outlined"
    />
  );
}

// Edit link for an authorable file: a sample.toml / acquisition.toml /
// md_run.toml warning row jumps straight into the matching authoring form,
// auto-loaded by id (issue 07). Acquisition identity is composite, so the
// link carries both ids (mirrors the acquisition detail-page "Edit
// acquisition.toml" link). An md_run_toml row without a resolvable md_run_id
// (e.g. a deprecated legacy [[md_run]] block, which names no single run) has
// no link either. Other file kinds (mdoc, mrc, run-scope, …) have no form —
// returns null.
export function authorLinkFor(
  group: Pick<
    IssueGroup,
    'file_kind' | 'sample_id' | 'acquisition_id' | 'md_run_id'
  >
): { to: string; search: Record<string, string> } | null {
  if (group.file_kind === 'sample_toml' && group.sample_id) {
    return {
      to: '/manage/author',
      search: { tab: 'sample', id: group.sample_id }
    };
  }
  if (
    group.file_kind === 'acquisition_toml' &&
    group.sample_id &&
    group.acquisition_id
  ) {
    return {
      to: '/manage/author',
      search: {
        tab: 'acquisition',
        id: group.acquisition_id,
        sampleId: group.sample_id
      }
    };
  }
  if (group.file_kind === 'md_run_toml' && group.md_run_id) {
    return {
      to: '/manage/author',
      search: { tab: 'md_run', id: group.md_run_id }
    };
  }
  return null;
}

// `file_kind` chip for a regrouped SampleWarningRow. When the row itself is
// authorable (sample.toml / md_run.toml — no acquisition id required) an
// "Edit file" link sits beside the chip; acquisition_toml rows instead get
// their edit action per-acquisition, in `AcquisitionListCell`.
export function RowFileCell({
  fileKind,
  sampleId,
  mdRunId
}: {
  readonly fileKind: string;
  readonly sampleId: string | null;
  readonly mdRunId: string | null;
}) {
  const link = authorLinkFor({
    file_kind: fileKind,
    sample_id: sampleId,
    acquisition_id: null,
    md_run_id: mdRunId
  });
  return (
    <Stack alignItems="center" direction="row" spacing={1}>
      <Chip
        label={fileKind}
        size="small"
        sx={{ fontFamily: 'monospace', fontSize: 11 }}
        variant="outlined"
      />
      {link ? (
        <CustomLink
          search={link.search}
          sx={{ whiteSpace: 'nowrap' }}
          to={link.to}
          variant="body2"
        >
          Edit file
        </CustomLink>
      ) : null}
    </Stack>
  );
}

// Representative message, truncated with the full text on hover — messages
// often embed a file/folder name that varies per acquisition (see
// `AcquisitionListCell` for the per-acquisition text).
export function MessageCell({ message }: { readonly message: string }) {
  return (
    <Tooltip title={message}>
      <Typography
        sx={{
          display: 'block',
          maxWidth: 320,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}
        variant="body2"
      >
        {message}
      </Typography>
    </Tooltip>
  );
}

// Sample link for a regrouped SampleWarningRow — acquisitions render
// separately, in `AcquisitionListCell`.
export function SampleCell({ sampleId }: { readonly sampleId: string | null }) {
  if (sampleId == null) {
    return (
      <Typography color="text.secondary" variant="body2">
        Scan (run-level)
      </Typography>
    );
  }
  return (
    <CustomLink params={{ sampleId }} to="/samples/$sampleId">
      {sampleId}
    </CustomLink>
  );
}

// Category chip — the stable, filename-free part of a warning (message text
// often embeds a specific file/folder name and stays per-acquisition).
export function CategoryChip({ category }: { readonly category: string }) {
  return (
    <Chip
      label={category.replaceAll('_', ' ')}
      size="small"
      sx={{ fontFamily: 'monospace', fontSize: 11 }}
      variant="outlined"
    />
  );
}

// Every acquisition affected by a sample+category warning row: name (linking
// to the acquisition detail page), a copy-path button, and — where an
// authoring form exists for this row's file_kind — an edit-metadata icon.
// A dash means the warning is sample- or run-level, with no acquisition to
// list. A message differing from the row's representative text (filenames
// vary) shows on hover rather than repeating a whole extra column.
export function AcquisitionListCell({
  row
}: {
  readonly row: {
    sample_id: string | null;
    md_run_id: string | null;
    file_kind: string;
    acquisitions: AffectedAcquisition[];
    message: string;
  };
}) {
  if (row.acquisitions.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        —
      </Typography>
    );
  }
  return (
    <Stack spacing={0.75}>
      {row.acquisitions.map(acq => {
        const ownMessage = acq.messages.join('; ');
        const differs = ownMessage !== row.message;
        const editLink = authorLinkFor({
          file_kind: row.file_kind,
          sample_id: row.sample_id,
          acquisition_id: acq.acquisition_id,
          md_run_id: row.md_run_id
        });
        return (
          <Stack
            alignItems="center"
            direction="row"
            key={acq.acquisition_id}
            spacing={0.25}
          >
            <Tooltip title={differs ? ownMessage : ''}>
              <CustomLink
                params={{ acquisitionId: acq.acquisition_id }}
                search={{ sampleId: row.sample_id ?? '' }}
                to="/acquisitions/$acquisitionId"
              >
                {acq.acquisition_id}
              </CustomLink>
            </Tooltip>
            {acq.acquisition_path ? (
              <CopyIconButton text={acq.acquisition_path} tooltip="Copy path" />
            ) : null}
            {editLink ? (
              <Tooltip title="Edit metadata">
                <IconButtonLink
                  aria-label="Edit metadata"
                  search={editLink.search}
                  size="small"
                  to={editLink.to}
                >
                  <EditNoteIcon fontSize="small" />
                </IconButtonLink>
              </Tooltip>
            ) : null}
          </Stack>
        );
      })}
    </Stack>
  );
}

// "Still present as of" (plan §9.7): when the owner was re-evaluated this run
// (`last_seen_run_id === latest_run_id`) show the global latest-scan timestamp;
// otherwise the owner was skipped — show its stale `last_seen_at` with a
// tooltip explaining it wasn't re-checked.
export function StillPresentCell({
  reEvaluated,
  timestamp
}: {
  readonly reEvaluated: boolean;
  readonly timestamp: number | null | undefined;
}) {
  if (reEvaluated) {
    return (
      <Typography sx={{ whiteSpace: 'nowrap' }} variant="body2">
        {formatTs(timestamp)}
      </Typography>
    );
  }
  return (
    <Tooltip title="owner skipped — not re-checked">
      <Typography
        sx={{ whiteSpace: 'nowrap', color: 'warning.main' }}
        variant="body2"
      >
        {formatTs(timestamp)}
      </Typography>
    </Tooltip>
  );
}
