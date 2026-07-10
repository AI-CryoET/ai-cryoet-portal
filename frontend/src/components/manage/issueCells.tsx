import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import type { IssueGroup } from '~/types'

// Issue timestamps are Unix seconds; render in the viewer's locale.
export function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  return new Date(seconds * 1000).toLocaleString(undefined, { timeZoneName: 'short' })
}

// First-seen wants a date-only reading (matches the wireframe's "2026-06-18").
export function formatDate(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  return new Date(seconds * 1000).toLocaleDateString()
}

export function SeverityPill({ severity }: { severity: IssueGroup['severity'] }) {
  return (
    <Chip
      label={severity}
      size="small"
      color={severity === 'error' ? 'error' : 'warning'}
      variant="outlined"
    />
  )
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
  group: IssueGroup,
): { to: string; search: Record<string, string> } | null {
  if (group.file_kind === 'sample_toml' && group.sample_id) {
    return { to: '/author', search: { tab: 'sample', id: group.sample_id } }
  }
  if (
    group.file_kind === 'acquisition_toml' &&
    group.sample_id &&
    group.acquisition_id
  ) {
    return {
      to: '/author',
      search: {
        tab: 'acquisition',
        id: group.acquisition_id,
        sampleId: group.sample_id,
      },
    }
  }
  if (group.file_kind === 'md_run_toml' && group.md_run_id) {
    return { to: '/author', search: { tab: 'md_run', id: group.md_run_id } }
  }
  return null
}

// `file_kind` chip + a truncated, monospace `file_path` beneath it. For an
// authorable file an "Edit file" link sits to the right of the chip,
// jumping into its authoring form (issue 07).
export function FileCell({ group }: { group: IssueGroup }) {
  const link = authorLinkFor(group)
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Chip
          label={group.file_kind}
          size="small"
          variant="outlined"
          sx={{ fontFamily: 'monospace', fontSize: 11 }}
        />
        {link ? (
          <CustomLink
            to={link.to}
            search={link.search}
            variant="body2"
            sx={{ whiteSpace: 'nowrap' }}
          >
            Edit file
          </CustomLink>
        ) : null}
      </Stack>
      {group.file_path ? (
        <Tooltip title={group.file_path}>
          <Typography
            variant="caption"
            sx={{
              fontFamily: 'monospace',
              color: 'text.secondary',
              display: 'block',
              maxWidth: 240,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {group.file_path}
          </Typography>
        </Tooltip>
      ) : null}
    </Stack>
  )
}

// Sample / acquisition link. Acquisition groups read like "sample · acq".
export function EntityCell({ group }: { group: IssueGroup }) {
  if (group.sample_id == null) {
    // Run-scope issue — no entity to link to.
    return (
      <Typography variant="body2" color="text.secondary">
        {group.scope === 'run' ? 'Scan (run-level)' : '—'}
      </Typography>
    )
  }
  if (group.acquisition_id) {
    return (
      <CustomLink
        to="/acquisitions/$acquisitionId"
        params={{ acquisitionId: group.acquisition_id }}
        search={{ sampleId: group.sample_id }}
      >
        {`${group.sample_id} · ${group.acquisition_id}`}
      </CustomLink>
    )
  }
  return (
    <CustomLink to="/samples/$sampleId" params={{ sampleId: group.sample_id }}>
      {group.sample_id}
    </CustomLink>
  )
}

// The bulleted list of issue messages within a group.
export function IssuesCell({ group }: { group: IssueGroup }) {
  const color = group.severity === 'error' ? 'error.main' : 'warning.main'
  return (
    <Box
      component="ul"
      sx={{ m: 0, pl: 2, color, '& code': { fontFamily: 'monospace' } }}
    >
      {group.issues.map((issue, i) => (
        <Typography key={i} component="li" variant="body2">
          {issue.message}
        </Typography>
      ))}
    </Box>
  )
}

// "Still present as of" (plan §9.7): when the owner was re-evaluated this run
// (`last_seen_run_id === latest_run_id`) show the global latest-scan timestamp;
// otherwise the owner was skipped — show its stale `last_seen_at` with a
// tooltip explaining it wasn't re-checked.
export function StillPresentCell({ group }: { group: IssueGroup }) {
  const reEvaluated =
    group.latest_run_id != null &&
    group.last_seen_run_id === group.latest_run_id
  if (reEvaluated) {
    return (
      <Typography variant="body2" sx={{ whiteSpace: 'nowrap' }}>
        {formatTs(group.latest_scan_at)}
      </Typography>
    )
  }
  return (
    <Tooltip title="owner skipped — not re-checked">
      <Typography
        variant="body2"
        sx={{ whiteSpace: 'nowrap', color: 'warning.main' }}
      >
        {formatTs(group.last_seen_at)}
      </Typography>
    </Tooltip>
  )
}

// Stable row identity across re-fetches: entity + file_kind uniquely keys a
// group (matches the backend's grouping).
export function issueRowId(group: IssueGroup): string {
  return [
    group.scope,
    group.sample_id ?? '',
    group.acquisition_id ?? '',
    group.file_kind,
  ].join('|')
}
