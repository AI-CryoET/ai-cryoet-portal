import { useState, type ReactNode } from 'react';
import {
  Box,
  CircularProgress,
  Modal,
  Tooltip,
  Typography
} from '@mui/material';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import type { AcquisitionOut } from '~/types';

type Size = number | string;

// Shared grey-box placeholder used wherever a representative image or viewer is
// missing (samples table, acquisition rows, sample-detail hero, acquisition
// tilt-series slot). Uses theme tokens (`action.hover` / `text.disabled`)
// rather than literal greys so it tracks the palette. Pass `icon` / `label` to
// hint at what will eventually fill the slot (e.g. a tilt-series viewer).
export function ThumbnailPlaceholder({
  width = 56,
  height = 40,
  aspectRatio,
  icon,
  label
}: {
  readonly width?: Size;
  readonly height?: Size;
  // When set, the slot is sized by aspect ratio (e.g. `1` for a square) against
  // its width instead of a fixed height.
  readonly aspectRatio?: Size;
  readonly icon?: ReactNode;
  readonly label?: string;
}) {
  return (
    <Box
      sx={{
        width,
        ...(aspectRatio != null ? { aspectRatio } : { height }),
        borderRadius: 1,
        bgcolor: 'action.hover',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.5,
        alignItems: 'center',
        justifyContent: 'center',
        color: 'text.disabled'
      }}
    >
      {icon ?? <ImageOutlinedIcon fontSize="small" />}
      {label ? (
        <Typography color="text.disabled" variant="caption">
          {label}
        </Typography>
      ) : null}
    </Box>
  );
}

// Full-screen enlarged view. When a `highResSrc` is given it's the preferred
// image, but it's fetched on demand and can be slow — so we keep showing the
// already-loaded `src` thumbnail (scaled up) with a loading spinner over it
// until the high-res image arrives, then swap it in. With no `highResSrc` (or
// if it fails to load) the thumbnail is shown on its own.
function ThumbnailLightbox({
  open,
  src,
  highResSrc,
  alt = '',
  onClose
}: {
  readonly open: boolean;
  readonly src: string;
  readonly highResSrc?: string | null;
  readonly alt?: string;
  readonly onClose: () => void;
}) {
  const [hiResLoaded, setHiResLoaded] = useState(false);
  const [hiResFailed, setHiResFailed] = useState(false);

  const wantHiRes = highResSrc != null && highResSrc !== src && !hiResFailed;
  const showHiRes = wantHiRes && hiResLoaded;
  const loading = wantHiRes && !hiResLoaded;

  return (
    <Modal onClose={onClose} open={open}>
      <Box
        onClick={onClose}
        sx={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          outline: 'none'
        }}
      >
        <Box sx={{ position: 'relative', display: 'flex' }}>
          <Box
            alt={alt}
            component="img"
            src={showHiRes ? (highResSrc as string) : src}
            sx={{
              maxWidth: '90vw',
              maxHeight: '90vh',
              objectFit: 'contain',
              borderRadius: 2,
              display: 'block'
            }}
          />
          {/* Off-screen probe that drives the swap once the high-res image is
              decoded; rendering it (rather than swapping `src` directly) keeps
              the thumbnail visible the whole time it's loading. */}
          {wantHiRes && !hiResLoaded ? (
            <Box
              alt=""
              aria-hidden
              component="img"
              onError={() => setHiResFailed(true)}
              onLoad={() => setHiResLoaded(true)}
              src={highResSrc as string}
              sx={{ display: 'none' }}
            />
          ) : null}
          {loading ? (
            <Box
              sx={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              <CircularProgress />
            </Box>
          ) : null}
        </Box>
      </Box>
    </Modal>
  );
}

// Renders an image, falling back to the placeholder when no `src` is given or
// the request fails (e.g. the preview endpoint returns 422 for EER-only tilt
// series). Keeps the same footprint either way so table rows don't jump.
// Pass `clickable` to let users open a full-screen lightbox on click.
// Pass `tooltipTitle` to show a tooltip that auto-dismisses when the lightbox opens.
// Pass `lightboxSrc` to enlarge a different (e.g. higher-resolution, on-demand)
// image than the one displayed — it's only fetched when the lightbox opens
// (the lightbox mounts on demand), and the thumbnail is shown with a spinner
// until it arrives. When omitted, the lightbox simply enlarges the thumbnail.
export function PreviewThumbnail({
  src,
  lightboxSrc,
  alt = '',
  width = 56,
  height = 40,
  aspectRatio,
  clickable = false,
  tooltipTitle,
  objectFit = 'cover',
  elevated = true,
  placeholderIcon,
  placeholderLabel
}: {
  readonly src?: string | null;
  readonly lightboxSrc?: string | null;
  readonly alt?: string;
  readonly width?: Size;
  readonly height?: Size;
  // When set, the image is sized by aspect ratio (e.g. `1` for a square)
  // against its width instead of a fixed height.
  readonly aspectRatio?: Size;
  readonly clickable?: boolean;
  readonly tooltipTitle?: string;
  readonly objectFit?: 'cover' | 'contain';
  // Whether to draw the drop-shadow "card" behind the loaded image. On by
  // default for table/list thumbnails; turn off where the image should fill
  // its slot edge-to-edge.
  readonly elevated?: boolean;
  readonly placeholderIcon?: ReactNode;
  readonly placeholderLabel?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  if (!src || failed) {
    return (
      <ThumbnailPlaceholder
        aspectRatio={aspectRatio}
        height={height}
        icon={placeholderIcon}
        label={placeholderLabel}
        width={width}
      />
    );
  }

  const img = (
    <Box
      alt={alt}
      component="img"
      onClick={clickable ? () => setLightboxOpen(true) : undefined}
      onError={() => setFailed(true)}
      onLoad={() => setLoaded(true)}
      src={src}
      sx={{
        width,
        ...(aspectRatio != null ? { aspectRatio } : { height }),
        objectFit,
        borderRadius: 1,
        display: 'block',
        ...(loaded
          ? elevated
            ? { boxShadow: '0 2px 8px rgba(0,0,0,0.18)' }
            : {}
          : { bgcolor: 'action.hover' }),
        ...(clickable && { cursor: 'pointer' })
      }}
    />
  );

  return (
    <>
      {tooltipTitle ? (
        <Tooltip open={lightboxOpen ? false : undefined} title={tooltipTitle}>
          <span>{img}</span>
        </Tooltip>
      ) : (
        img
      )}
      {clickable && lightboxOpen ? (
        <ThumbnailLightbox
          alt={alt}
          highResSrc={lightboxSrc}
          onClose={() => setLightboxOpen(false)}
          open={lightboxOpen}
          src={src}
        />
      ) : null}
    </>
  );
}

// ── Thumbnail URL helpers ────────────────────────────────────────────────

const enc = (x: string) => x.split('/').map(encodeURIComponent).join('/');

// Pre-generated per-acquisition cached thumbnail (the median tilt-series
// image). Relpath scheme must match catalog/thumbnails._relpath:
// {sample}/{acq}.png. Used in tables/lists and the sample-detail hero where
// fast cached loads matter.
export function acquisitionThumbnailUrl(s: string, a: string): string {
  return `/api/thumbnails/${enc(s)}/${enc(a)}.png`;
}

export function thumbnailUrl(relpath?: string | null): string | null {
  return relpath
    ? `/api/thumbnails/${relpath.split('/').map(encodeURIComponent).join('/')}`
    : null;
}

// Cached OVITO MD-run preview PNG served from the scanner-generated cache.
// Pass an MD run's `preview_path` relpath ({sample}/{run}.png); returns null
// when the run (or sample) has no rendered preview.
export function mdPreviewUrl(relpath?: string | null): string | null {
  return relpath ? `/api/md-previews/${enc(relpath)}` : null;
}

// On-demand median/middle tilt-series image (rendered fresh at higher
// resolution from the zarr/.st/Frames stack). Used on the acquisition-detail
// hero, where the click-to-enlarge lightbox benefits from the sharper render.
// Returns 422 when no stack artifact is reachable.
export function tiltSeriesPreviewUrl(s: string, a: string, ts: string): string {
  return `/api/tilt-series/${enc(s)}/${enc(a)}/${enc(ts)}/preview.png`;
}

// On-demand tomogram center-XY slice — distinct per tomogram, used in the
// tomograms table where each row is its own reconstruction. `g` is the
// Reconstructions/{group}/ the tomogram lives in: the id is only a file stem,
// so two groups can each hold e.g. `denoised`.
export function tomogramPreviewUrl(
  s: string,
  a: string,
  g: string,
  t: string
): string {
  return `/api/tomograms/${enc(s)}/${enc(a)}/${enc(g)}/${enc(t)}/preview.png`;
}

// On-demand annotation center-XY slice — the annotation's `.mrc` artifact
// rendered like a tomogram. Used in the annotations sub-table. Returns 422
// when the annotation has no `.mrc` (e.g. sparse/point-only annotations), in
// which case PreviewThumbnail falls back to the grey placeholder.
export function annotationPreviewUrl(
  s: string,
  a: string,
  g: string,
  ann: string
): string {
  return `/api/annotations/${enc(s)}/${enc(a)}/${enc(g)}/${enc(ann)}/preview.png`;
}

// First tilt series of an acquisition — the representative used for the
// median-tilt hero image.
export function acquisitionRepTiltSeriesId(a: AcquisitionOut): string | null {
  return a.tilt_series[0]?.tilt_series_id ?? null;
}

// Tilt geometry is an acquisition-level property (shared by all the
// acquisition's tilt series), so the polar plot is keyed on the acquisition.
// Route prefix is /acquisitions (api/main.py); frontend proxies under /api.
// Returns 422 when the acquisition has no cached tilt_angles (EER-only).
export function acquisitionPolarUrl(s: string, a: string): string {
  return `/api/acquisitions/${enc(s)}/${enc(a)}/polar.png`;
}
