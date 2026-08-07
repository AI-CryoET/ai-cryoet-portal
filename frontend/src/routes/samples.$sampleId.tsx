import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import {
  Box,
  Breadcrumbs,
  Divider,
  Paper,
  Stack,
  Typography
} from '@mui/material';
import type { SampleDetail } from '~/types';
import { CustomLink } from '~/components/CustomLink';
import {
  PreviewThumbnail,
  acquisitionThumbnailUrl,
  thumbnailUrl,
  tiltSeriesPreviewUrl,
  acquisitionRepTiltSeriesId,
  mdPreviewBySampleUrl
} from '~/components/common/Thumbnail';
import { FileglancerPathSection } from '~/components/common/FileglancerPathSection';
import { DetailHero } from '~/components/common/DetailHero';
import { DetailPageHeader } from '~/components/common/DetailPageHeader';
import { MetadataDrawer } from '~/components/common/MetadataDrawer';
import { MetadataSectionList } from '~/components/common/MetadataSectionList';
import { sampleMetadataSections } from '~/components/common/metadataSections';
import { SampleAcquisitionsTable } from '~/components/samples/SampleAcquisitionsTable';
import { EntityFreshnessCard } from '~/components/manage/EntityFreshnessCard';
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
  useSampleDetailQuery,
  useSampleWarningsQuery
} from '~/utils/queryOptions';

export const Route = createFileRoute('/samples/$sampleId')({
  loader: ({ context: { queryClient }, params: { sampleId } }) =>
    Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId))
    ]),
  component: SampleDetailRoute
});

// Fallback for DB rows scanned before `sample.path` existed: derive it from an
// acquisition path, which the scanner stores as `{sample_dir}/{acquisition_id}`
// — so the sample directory is its parent. Prefer `sample.path` when present.
function deriveSamplePath(sample: SampleDetail): string | null {
  const acqPath = sample.acquisitions.find(a => a.path)?.path;
  if (!acqPath) {
    return null;
  }
  const trimmed = acqPath.replace(/\/+$/, '');
  const idx = trimmed.lastIndexOf('/');
  return idx > 0 ? trimmed.slice(0, idx) : trimmed;
}

function countTomograms(sample: SampleDetail): number {
  return sample.acquisitions.reduce(
    (sum, a) =>
      sum + a.raw_tomograms.length + a.post_processed_tomograms.length,
    0
  );
}

function countAnnotations(sample: SampleDetail): number {
  return sample.acquisitions.reduce((sum, a) => sum + a.annotations.length, 0);
}

function SampleContentsCard({ sample }: { readonly sample: SampleDetail }) {
  const rows: Array<[string, number]> = [
    ['Acquisitions', sample.acquisitions.length],
    ['Tomograms', countTomograms(sample)],
    ['Annotations', countAnnotations(sample)]
  ];
  return (
    <Paper
      elevation={0}
      sx={{
        px: 2.5,
        py: 2,
        borderRadius: 2,
        maxWidth: 320,
        bgcolor: 'grey.100'
      }}
    >
      <Typography gutterBottom variant="subtitle2">
        Sample contents
      </Typography>
      <Stack spacing={0.5}>
        {rows.map(([label, value]) => (
          <Box
            key={label}
            sx={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}
          >
            <Typography color="text.secondary" variant="body2">
              {label}
            </Typography>
            <Typography variant="body2">{value.toLocaleString()}</Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  );
}

function SampleDetailRoute() {
  const { sampleId } = Route.useParams();
  const { data: sample } = useSampleDetailQuery(sampleId);
  const { data: warnings } = useSampleWarningsQuery(sampleId);
  const [metadataOpen, setMetadataOpen] = useState(false);

  const samplePath = sample.path ?? deriveSamplePath(sample);

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink color="inherit" to="/">
          Home
        </CustomLink>
        <CustomLink
          color="inherit"
          to={
            sample.data_source === 'simulation'
              ? '/md-simulation'
              : '/experimental'
          }
        >
          Browse
        </CustomLink>
        <Typography color="text.primary">{sampleId}</Typography>
      </Breadcrumbs>

      {/* ── Title section ──────────────────────────────────────────── */}
      <DetailPageHeader
        description={sample.description}
        editLink={
          <CustomLink
            search={{ tab: 'sample', id: sampleId }}
            to="/manage/author"
          >
            Edit sample.toml
          </CustomLink>
        }
        onViewMetadata={() => setMetadataOpen(true)}
        title={sampleId}
        warning={
          warnings.length > 0
            ? {
                // Opens the warnings page with outstanding issues filtered to
                // this sample (seeds the `q` search param there).
                href: `/manage/warnings?q=${encodeURIComponent(sampleId)}`,
                text: "*There are warnings for this sample's metadata. Click to view"
              }
            : null
        }
      />

      <Divider />

      {/* ── Details summary ────────────────────────────────────────── */}
      <DetailHero
        details={
          <FileglancerPathSection path={samplePath}>
            <Stack spacing={2}>
              <SampleContentsCard sample={sample} />
              <EntityFreshnessCard kind="sample" status={sample.scan_status} />
            </Stack>
          </FileglancerPathSection>
        }
        thumbnail={(() => {
          const sorted = [...sample.acquisitions].sort((a, b) =>
            a.acquisition_id.localeCompare(b.acquisition_id)
          );
          const firstWithTs = sorted.find(
            a => acquisitionRepTiltSeriesId(a) !== null
          );
          const tsId = firstWithTs
            ? acquisitionRepTiltSeriesId(firstWithTs)
            : null;
          // Simulation samples show the trajectory-level OVITO preview from the
          // portal cache (resolved by sample prefix) at the sample hero — the
          // per-acquisition tilt-series slice belongs on the acquisition page.
          // Now that synthetic acquisitions carry real tilt series, this keeps
          // the two levels visually distinct.
          const mdPreview =
            sample.data_source === 'simulation'
              ? mdPreviewBySampleUrl(sample.sample_id, sample.path)
              : null;
          // Simulation → OVITO preview. Otherwise prefer the acquisition with a
          // tilt series: its cached 512px thumbnail displays, and the sharper
          // on-demand render is fetched only when the lightbox opens. When no
          // acquisition declares a tilt series we still show the sample's
          // representative cached thumbnail (rendered from raw Frames/); the
          // lightbox then just enlarges that thumbnail, since the sharper render
          // needs a tilt_series_id.
          const showMd = mdPreview !== null;
          const src = showMd
            ? mdPreview
            : firstWithTs
              ? acquisitionThumbnailUrl(
                  sample.sample_id,
                  firstWithTs.acquisition_id
                )
              : thumbnailUrl(sample.thumbnail_path);
          // The sharper on-demand render only applies to the tilt-series
          // thumbnail; the OVITO preview just enlarges itself in the lightbox.
          const lightboxSrc =
            !showMd && firstWithTs && tsId
              ? tiltSeriesPreviewUrl(
                  sample.sample_id,
                  firstWithTs.acquisition_id,
                  tsId
                )
              : null;
          const caption = showMd
            ? 'OVITO preview of the MD simulation'
            : 'Middle image of the representative tilt series';
          return (
            <Box>
              <PreviewThumbnail
                alt={
                  showMd
                    ? `OVITO preview for ${sample.sample_id}`
                    : `Middle tilt-series image for ${sample.sample_id}`
                }
                aspectRatio={1}
                clickable
                elevated={false}
                lightboxSrc={lightboxSrc}
                objectFit="contain"
                src={src}
                width="100%"
              />
              <Typography
                color="text.secondary"
                sx={{ mt: 0.75, display: 'block' }}
                variant="caption"
              >
                {caption}
              </Typography>
            </Box>
          );
        })()}
      />

      <Divider />

      {/* ── Acquisitions ───────────────────────────────────────────── */}
      <Box>
        {/* Plain heading (no band), matching the acquisition page's
            "Reconstructions" title. */}
        <Typography component="h2" sx={{ mb: 2 }} variant="h6">
          Acquisitions ({sample.acquisitions.length.toLocaleString()})
        </Typography>
        <SampleAcquisitionsTable
          acquisitions={sample.acquisitions}
          sampleId={sampleId}
        />
      </Box>

      <MetadataDrawer
        eyebrow="Sample details"
        onClose={() => setMetadataOpen(false)}
        open={metadataOpen}
        title={sampleId}
      >
        <MetadataSectionList sections={sampleMetadataSections(sample)} />
      </MetadataDrawer>
    </Stack>
  );
}
