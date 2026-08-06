import { useState } from 'react'
import { Button, CircularProgress, Tooltip } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import type { ViewerLaunchOut } from '../../types'
import { apiFetch } from '../../utils/api'

export type NeuroglancerSource =
  // `groupId` is the Reconstructions/{reconstruction_alignment_id}/ segment —
  // required for tomograms and annotations (their ids are only file stems,
  // unique within the group), absent for tilt series.
  | { kind: 'launch'; entity: 'tomogram' | 'annotation'; sampleId: string; acquisitionId: string; groupId: string; entityId: string }
  | { kind: 'launch'; entity: 'tilt-series'; sampleId: string; acquisitionId: string; entityId: string }
  | { kind: 'zarr-link'; url: string }
  | null

const LAUNCH_SEGMENT: Record<Extract<NeuroglancerSource, { kind: 'launch' }>['entity'], string> = {
  tomogram: 'tomograms',
  'tilt-series': 'tilt-series',
  annotation: 'annotations',
}

interface NeuroglancerButtonProps {
  source: NeuroglancerSource
  label?: string
}

function launchNeuroglancer(source: Extract<NeuroglancerSource, { kind: 'launch' }>): Promise<ViewerLaunchOut> {
  const segment = LAUNCH_SEGMENT[source.entity]
  const group = 'groupId' in source ? `/${source.groupId}` : ''
  return apiFetch<ViewerLaunchOut>(
    `/${segment}/${source.sampleId}/${source.acquisitionId}${group}/${source.entityId}/neuroglancer`,
    { method: 'POST' },
  )
}

export function NeuroglancerButton(props: NeuroglancerButtonProps) {
  const { source, label = 'View in Neuroglancer' } = props
  const [launchError, setLaunchError] = useState<string | null>(null)

  const mutation = useMutation({ mutationFn: launchNeuroglancer })

  if (source === null) {
    return (
      <Tooltip title="Neuroglancer link coming soon">
        {/* span wrapper so the tooltip still fires on the disabled button */}
        <span>
          <Button variant="contained" size="small" disabled>
            {label}
          </Button>
        </span>
      </Tooltip>
    )
  }

  if (source.kind === 'zarr-link') {
    return (
      <Button
        variant="contained"
        size="small"
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {label}
      </Button>
    )
  }

  // kind === 'launch'
  function handleClick() {
    setLaunchError(null)
    // Open blank window synchronously to avoid popup blocker.
    const w = window.open('about:blank', '_blank')
    const launchSource = source as Extract<NeuroglancerSource, { kind: 'launch' }>
    mutation.mutate(launchSource, {
      onSuccess(data) {
        // Tomograms and annotations return a fully-formed external viewer URL
        // (Fileglancer-hosted Neuroglancer + a precomputed:// source served by
        // mrc-server, with any bbox baked into the URL) — open it as-is. The
        // re-rooting below only applies to tilt-series, still served by the
        // API's own in-process Neuroglancer port.
        // ponytail: drop this branch once tilt-series goes stateless too.
        if (launchSource.entity === 'tomogram' || launchSource.entity === 'annotation') {
          w!.location.href = data.url
          return
        }
        // DEV-ONLY same-origin re-rooting (pairs with the Neuroglancer reverse
        // proxy in vite.config.ts).
        //
        // The backend returns an absolute Neuroglancer URL pointing at the API
        // host's own Neuroglancer port, e.g. http://<api-host>:8050/v/<token>/.
        // In dev we don't want the browser to hit that second port directly (it
        // may not be forwarded over an ssh / VS Code tunnel, or gets remapped to
        // a different local port — see vite.config.ts). The dev server proxies
        // Neuroglancer's root paths on THIS origin, so we keep only the path and
        // re-root it onto window.location.origin. This is safe because the
        // Neuroglancer client fetches its `python://` volume data relative to
        // the page origin, so everything rides the one already-forwarded port.
        //
        // NOTE: this assumes the dev proxy is present. In production Neuroglancer
        // is served on its own port and the backend URL would be used as-is, so
        // this rewrite would need revisiting for a non-dev deployment.
        const u = new URL(data.url)
        w!.location.href = window.location.origin + u.pathname + u.search + u.hash
      },
      onError() {
        w?.close()
        setLaunchError('Failed to launch viewer')
      },
    })
  }

  return (
    <Tooltip title={launchError ?? ''} open={!!launchError}>
      <span>
        <Button
          variant="contained"
          size="small"
          disabled={mutation.isPending}
          onClick={handleClick}
          startIcon={mutation.isPending ? <CircularProgress size={14} color="inherit" /> : undefined}
        >
          {label}
        </Button>
      </span>
    </Tooltip>
  )
}
