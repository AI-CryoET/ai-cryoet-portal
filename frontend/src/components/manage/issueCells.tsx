import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';
import EditNoteIcon from '@mui/icons-material/EditNote';
import { CustomLink, IconButtonLink } from '~/components/CustomLink';
import { CopyIconButton } from '~/components/common/CopyIconButton';
import type { IssueGroup } from '~/types';
import type {
  AffectedAcquisition,
  AffectedReconstruction,
  MessageScope,
  WarningMessage
} from './groupSampleWarnings';

// Path convention baked into the (shortened) assembler.py message strings:
// a reconstruction-alignment group always lives directly under its
// acquisition's `Reconstructions/<group>` folder. No stored `path` column
// exists on ReconstructionAlignmentORM, so this is derived client-side.
function reconstructionPath(
  acquisitionPath: string | null,
  reconstructionId: string
): string | null {
  return acquisitionPath
    ? `${acquisitionPath}/Reconstructions/${reconstructionId}`
    : null;
}

// Issue timestamps are Unix seconds; render in the viewer's locale.
export function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

// Single-line ellipsis truncation for cells that shouldn't wrap (name/id
// columns) — pairs with a Tooltip showing the full value. Also used inside a
// flex row (Stack), so callers should give the wrapping Box `minWidth: 0`.
const ellipsisSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  minWidth: 0
} as const;

// Wrap normally, then clamp to a fixed number of lines with an ellipsis.
const lineClampSx = (lines: number) =>
  ({
    display: '-webkit-box',
    WebkitLineClamp: lines,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
    minWidth: 0
  }) as const;

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
// md_run.toml warning jumps straight into the matching authoring form,
// auto-loaded by id (issue 07). Acquisition identity is composite, so the link
// carries both ids. Other file kinds (mdoc, mrc, run-scope, …) have no form —
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

// Warning type — plain wrapped text (no chip/pill), clamped to a couple of
// lines. Kept for the toolbar's warning-type filter labels and legacy callers.
export function WarningTypeCell({ category }: { readonly category: string }) {
  return (
    <Typography sx={lineClampSx(2)} variant="body2">
      {category.replaceAll('_', ' ')}
    </Typography>
  );
}

const EditMetadataLink = ({
  search
}: {
  readonly search: Record<string, string>;
}) => (
  <Tooltip title="Edit metadata">
    <IconButtonLink
      aria-label="Edit metadata"
      search={search}
      size="small"
      to="/manage/author"
    >
      <EditNoteIcon fontSize="small" />
    </IconButtonLink>
  </Tooltip>
);

// Sample link + (optional) copy-path/edit-metadata actions — used as a band
// header. `showActions` folds the sample.toml copy/edit in when the sample has
// a message of its own.
export function SampleCell({
  sampleId,
  samplePath = null,
  fileKind,
  mdRunId = null,
  showActions = false
}: {
  readonly sampleId: string | null;
  readonly samplePath?: string | null;
  readonly fileKind?: string;
  readonly mdRunId?: string | null;
  readonly showActions?: boolean;
}) {
  if (sampleId == null) {
    return (
      <Typography color="text.secondary" variant="body2">
        Scan (run-level)
      </Typography>
    );
  }
  const editLink =
    showActions && fileKind
      ? authorLinkFor({
          file_kind: fileKind,
          sample_id: sampleId,
          acquisition_id: null,
          md_run_id: mdRunId
        })
      : null;
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Box sx={ellipsisSx}>
        <CustomLink params={{ sampleId }} to="/samples/$sampleId">
          {sampleId}
        </CustomLink>
      </Box>
      {showActions && samplePath ? (
        <CopyIconButton text={samplePath} tooltip="Copy path" />
      ) : null}
      {editLink ? <EditMetadataLink search={editLink.search} /> : null}
    </Stack>
  );
}

export function EntityDash() {
  return (
    <Typography color="text.secondary" variant="body2">
      —
    </Typography>
  );
}

// A small circled S / A / R marking which data level a message applies to,
// replacing the plain bullet. Color-keyed by scope (not severity — that's a
// filter now).
const SCOPE_META: Record<
  MessageScope,
  { letter: string; label: string; color: string }
> = {
  sample: { letter: 'S', label: 'Sample-level message', color: 'grey.600' },
  acquisition: {
    letter: 'A',
    label: 'Acquisition-level message',
    color: 'primary.main'
  },
  reconstruction: {
    letter: 'R',
    label: 'Reconstruction-level message',
    color: 'secondary.main'
  }
};

export function ScopeIcon({ scope }: { readonly scope: MessageScope }) {
  const { letter, label, color } = SCOPE_META[scope];
  return (
    <Tooltip title={label}>
      <Box
        aria-label={label}
        sx={{
          flex: '0 0 auto',
          width: 18,
          height: 18,
          mt: '2px',
          borderRadius: '50%',
          bgcolor: color,
          color: 'common.white',
          fontSize: 11,
          fontWeight: 700,
          lineHeight: '18px',
          textAlign: 'center'
        }}
      >
        {letter}
      </Box>
    </Tooltip>
  );
}

// One or more warning messages, each on its own line with its scope icon.
// Wrapping, no truncation (the row grows taller instead).
export function MessageList({
  messages
}: {
  readonly messages: WarningMessage[];
}) {
  if (messages.length === 0) {
    return <EntityDash />;
  }
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      {messages.map((m, i) => (
        <Stack
          direction="row"
          key={`${i}-${m.text}`}
          spacing={0.75}
          sx={{ minWidth: 0 }}
        >
          <ScopeIcon scope={m.scope} />
          <Typography
            sx={{
              minWidth: 0,
              whiteSpace: 'normal',
              // Messages embed long, space-less file/folder paths; break them
              // mid-token so they wrap instead of overflowing the column.
              overflowWrap: 'anywhere'
            }}
            variant="body2"
          >
            {m.text}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

// Acquisition name + (optional) actions. `withActions` is true only when the
// acquisition owns a message of its own; when its name is merely a group header
// for reconstruction rows, the copy/edit icons (which would point at
// acquisition.toml) are dropped — the fix lives on the reconstruction.
export function AcqLabel({
  acq,
  sampleId,
  withActions
}: {
  readonly acq: AffectedAcquisition;
  readonly sampleId: string | null;
  readonly withActions: boolean;
}) {
  const editLink = withActions
    ? authorLinkFor({
        file_kind: acq.file_kind,
        sample_id: sampleId,
        acquisition_id: acq.acquisition_id,
        md_run_id: null
      })
    : null;
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Box sx={ellipsisSx}>
        <CustomLink
          params={{ acquisitionId: acq.acquisition_id }}
          search={{ sampleId: sampleId ?? '' }}
          to="/acquisitions/$acquisitionId"
        >
          {acq.acquisition_id}
        </CustomLink>
      </Box>
      {withActions && acq.acquisition_path ? (
        <CopyIconButton text={acq.acquisition_path} tooltip="Copy path" />
      ) : null}
      {editLink ? <EditMetadataLink search={editLink.search} /> : null}
    </Stack>
  );
}

// Reconstruction name (plain text, no detail page) + copy-path (derived,
// skipped when acquisition_path is null) + edit-metadata (reconstruction tab).
export function ReconLabel({
  acq,
  recon,
  sampleId
}: {
  readonly acq: AffectedAcquisition;
  readonly recon: AffectedReconstruction;
  readonly sampleId: string | null;
}) {
  const path = reconstructionPath(
    acq.acquisition_path,
    recon.reconstruction_alignment_id
  );
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Typography sx={ellipsisSx} variant="body2">
        {recon.reconstruction_alignment_id}
      </Typography>
      {path ? <CopyIconButton text={path} tooltip="Copy path" /> : null}
      <EditMetadataLink
        search={{
          tab: 'reconstruction',
          id: recon.reconstruction_alignment_id,
          sampleId: sampleId ?? '',
          acquisitionId: recon.acquisition_id
        }}
      />
    </Stack>
  );
}

// An md_run pseudo-entity, rendered in the Acquisition column (md_run isn't an
// acquisition, but it's sample-level context that needs its own edit link).
// Plain text id + edit-metadata (md_run tab); no detail page, no stored path.
export function MdRunLabel({
  mdRunId,
  sampleId
}: {
  readonly mdRunId: string;
  readonly sampleId: string | null;
}) {
  const editLink = authorLinkFor({
    file_kind: 'md_run_toml',
    sample_id: sampleId,
    acquisition_id: null,
    md_run_id: mdRunId
  });
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Typography sx={ellipsisSx} variant="body2">
        {mdRunId}
      </Typography>
      {editLink ? <EditMetadataLink search={editLink.search} /> : null}
    </Stack>
  );
}

// "Still present as of" (plan §9.7): when the owner was re-evaluated this run
// show the global latest-scan timestamp; otherwise show its stale `last_seen_at`
// with a tooltip explaining it wasn't re-checked.
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
      <Typography sx={{ whiteSpace: 'nowrap' }} variant="body2">
        {formatTs(timestamp)}
      </Typography>
    </Tooltip>
  );
}
