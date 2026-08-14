import { useState } from 'react';
import {
  Button,
  CircularProgress,
  Stack,
  Tooltip,
  Typography
} from '@mui/material';
import { useMutation } from '@tanstack/react-query';
import type { ViewerLaunchOut } from '../../types';
import { apiFetch } from '../../utils/api';

export type NeuroglancerSource =
  // `groupId` is the Reconstructions/{reconstruction_alignment_id}/ segment —
  // required since tomogram/annotation ids are only file stems, unique within
  // the group.
  | {
      kind: 'launch';
      entity: 'tomogram' | 'annotation';
      sampleId: string;
      acquisitionId: string;
      groupId: string;
      entityId: string;
    }
  | { kind: 'zarr-link'; url: string }
  | null;

const LAUNCH_SEGMENT: Record<
  Extract<NeuroglancerSource, { kind: 'launch' }>['entity'],
  string
> = {
  tomogram: 'tomograms',
  annotation: 'annotations'
};

interface NeuroglancerButtonProps {
  readonly source: NeuroglancerSource;
  readonly label?: string;
  // When set, the button is disabled and this text is shown as a tooltip and
  // as a warning caption underneath — used when launching would produce a
  // broken viewer (e.g. an MRC whose header has no voxel size). Takes
  // precedence over `source`.
  readonly disabledReason?: string | null;
}

function launchNeuroglancer(
  source: Extract<NeuroglancerSource, { kind: 'launch' }>
): Promise<ViewerLaunchOut> {
  const segment = LAUNCH_SEGMENT[source.entity];
  return apiFetch<ViewerLaunchOut>(
    `/${segment}/${source.sampleId}/${source.acquisitionId}/${source.groupId}/${source.entityId}/neuroglancer`,
    { method: 'POST' }
  );
}

export function NeuroglancerButton({
  source,
  label = 'View in Neuroglancer',
  disabledReason
}: NeuroglancerButtonProps) {
  const [launchError, setLaunchError] = useState<string | null>(null);

  const mutation = useMutation({ mutationFn: launchNeuroglancer });

  if (disabledReason) {
    return (
      <Stack alignItems="flex-end" spacing={0.5}>
        <Tooltip title={disabledReason}>
          {/* span wrapper so the tooltip still fires on the disabled button */}
          <span>
            <Button disabled size="small" variant="contained">
              {label}
            </Button>
          </span>
        </Tooltip>
        <Typography
          color="warning.main"
          sx={{ maxWidth: 200, textAlign: 'right' }}
          variant="caption"
        >
          {disabledReason}
        </Typography>
      </Stack>
    );
  }

  if (source === null) {
    return (
      <Tooltip title="Neuroglancer link coming soon">
        {/* span wrapper so the tooltip still fires on the disabled button */}
        <span>
          <Button disabled size="small" variant="contained">
            {label}
          </Button>
        </span>
      </Tooltip>
    );
  }

  if (source.kind === 'zarr-link') {
    return (
      <Button
        href={source.url}
        rel="noopener noreferrer"
        size="small"
        target="_blank"
        variant="contained"
      >
        {label}
      </Button>
    );
  }

  // kind === 'launch'
  function handleClick() {
    setLaunchError(null);
    // Open blank window synchronously to avoid popup blocker.
    const w = window.open('about:blank', '_blank');
    const launchSource = source as Extract<
      NeuroglancerSource,
      { kind: 'launch' }
    >;
    mutation.mutate(launchSource, {
      onSuccess(data) {
        // The backend returns a fully-formed external viewer URL
        // (Fileglancer-hosted Neuroglancer + a precomputed:// source served by
        // mrc-server, with any bbox baked into the URL) — open it as-is.
        w!.location.href = data.url;
      },
      onError() {
        w?.close();
        setLaunchError('Failed to launch viewer');
      }
    });
  }

  return (
    <Tooltip open={!!launchError} title={launchError ?? ''}>
      <span>
        <Button
          disabled={mutation.isPending}
          onClick={handleClick}
          size="small"
          startIcon={
            mutation.isPending ? (
              <CircularProgress color="inherit" size={14} />
            ) : undefined
          }
          variant="contained"
        >
          {label}
        </Button>
      </span>
    </Tooltip>
  );
}
