import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Divider, Paper, Stack, Typography } from '@mui/material'
import type { SampleDetail } from '~/types'
import { CustomLink } from '~/components/CustomLink'
import {
  PreviewThumbnail,
  acquisitionThumbnailUrl,
  thumbnailUrl,
  tiltSeriesPreviewUrl,
  acquisitionRepTiltSeriesId,
  mdPreviewBySampleUrl,
} from '~/components/common/Thumbnail'
import { FileglancerPathSection } from '~/components/common/FileglancerPathSection'
import { DetailHero } from '~/components/common/DetailHero'
import { DetailPageHeader } from '~/components/common/DetailPageHeader'
import { SectionHeading } from '~/components/common/SectionHeading'
import { MetadataDrawer } from '~/components/common/MetadataDrawer'
import { MetadataSectionList } from '~/components/common/MetadataSectionList'
import { sampleMetadataSections } from '~/components/common/metadataSections'
import { SampleAcquisitionsTable } from '~/components/samples/SampleAcquisitionsTable'
import { EntityFreshnessCard } from '~/components/manage/EntityFreshnessCard'
import {
  sampleDetailQueryOptions,
  sampleWarningsQueryOptions,
  useSampleDetailQuery,
  useSampleWarningsQuery,
} from '~/utils/queryOptions'

export const Route = createFileRoute('/samples/$sampleId')({
  loader: ({ context: { queryClient }, params: { sampleId } }) =>
    Promise.all([
      queryClient.ensureQueryData(sampleDetailQueryOptions(sampleId)),
      queryClient.ensureQueryData(sampleWarningsQueryOptions(sampleId)),
    ]),
  component: SampleDetailRoute,
})

// Fallback for DB rows scanned before `sample.path` existed: derive it from an
// acquisition path, which the scanner stores as `{sample_dir}/{acquisition_id}`
// — so the sample directory is its parent. Prefer `sample.path` when present.
function deriveSamplePath(sample: SampleDetail): string | null {
  const acqPath = sample.acquisitions.find((a) => a.path)?.path
  if (!acqPath) return null
  const trimmed = acqPath.replace(/\/+$/, '')
  const idx = trimmed.lastIndexOf('/')
  return idx > 0 ? trimmed.slice(0, idx) : trimmed
}

function countTomograms(sample: SampleDetail): number {
  return sample.acquisitions.reduce(
    (sum, a) => sum + (a.raw_tomogram ? 1 : 0) + a.post_processed_tomograms.length,
    0,
  )
}

function countAnnotations(sample: SampleDetail): number {
  return sample.acquisitions.reduce((sum, a) => sum + a.annotations.length, 0)
}

function SampleContentsCard(props: { sample: SampleDetail }) {
  const { sample } = props
  const rows: Array<[string, number]> = [
    ['Acquisitions', sample.acquisitions.length],
    ['Tomograms', countTomograms(sample)],
    ['Annotations', countAnnotations(sample)],
  ]
  return (
    <Paper
      elevation={0}
      sx={{ px: 2.5, py: 2, borderRadius: 2, maxWidth: 320, bgcolor: 'grey.100' }}
    >
      <Typography variant="subtitle2" gutterBottom>
        Sample contents
      </Typography>
      <Stack spacing={0.5}>
        {rows.map(([label, value]) => (
          <Box
            key={label}
            sx={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}
          >
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="body2">{value.toLocaleString()}</Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function SampleDetailRoute() {
  const { sampleId } = Route.useParams()
  const { data: sample } = useSampleDetailQuery(sampleId)
  const { data: warnings } = useSampleWarningsQuery(sampleId)
  const [metadataOpen, setMetadataOpen] = useState(false)

  const samplePath = sample.path ?? deriveSamplePath(sample)

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit">
          Home
        </CustomLink>
        <CustomLink
          to={sample.data_source === 'simulation' ? '/md-simulation' : '/experimental'}
          color="inherit"
        >
          Browse
        </CustomLink>
        <Typography color="text.primary">{sampleId}</Typography>
      </Breadcrumbs>

      {/* ── Title section ──────────────────────────────────────────── */}
      <DetailPageHeader
        title={sampleId}
        onViewMetadata={() => setMetadataOpen(true)}
        warning={
          warnings.length > 0
            ? {
                // Opens the manage page with outstanding issues filtered to
                // this sample (read from the URL search params there).
                href: `/manage?sample=${encodeURIComponent(sampleId)}`,
                text: "*There are warnings for this sample's metadata. Click to view",
              }
            : null
        }
        description={sample.description}
      />

      <Box>
        <CustomLink to="/author" search={{ tab: 'sample', id: sampleId }}>
          Edit sample.toml
        </CustomLink>
      </Box>

      <Divider />

      {/* ── Details summary ────────────────────────────────────────── */}
      <DetailHero
        thumbnail={(() => {
          const sorted = [...sample.acquisitions].sort((a, b) =>
            a.acquisition_id.localeCompare(b.acquisition_id),
          )
          const firstWithTs = sorted.find(
            (a) => acquisitionRepTiltSeriesId(a) !== null,
          )
          const tsId = firstWithTs ? acquisitionRepTiltSeriesId(firstWithTs) : null
          // Simulation samples show the trajectory-level OVITO preview from the
          // portal cache (resolved by sample prefix) at the sample hero — the
          // per-acquisition tilt-series slice belongs on the acquisition page.
          // Now that synthetic acquisitions carry real tilt series, this keeps
          // the two levels visually distinct.
          const mdPreview =
            sample.data_source === 'simulation'
              ? mdPreviewBySampleUrl(sample.sample_id, sample.path)
              : null
          // Simulation → OVITO preview. Otherwise prefer the acquisition with a
          // tilt series: its cached 512px thumbnail displays, and the sharper
          // on-demand render is fetched only when the lightbox opens. When no
          // acquisition declares a tilt series we still show the sample's
          // representative cached thumbnail (rendered from raw Frames/); the
          // lightbox then just enlarges that thumbnail, since the sharper render
          // needs a tilt_series_id.
          const showMd = mdPreview !== null
          const src =
            showMd
              ? mdPreview
              : firstWithTs
                ? acquisitionThumbnailUrl(
                    sample.sample_id,
                    firstWithTs.acquisition_id,
                  )
                : thumbnailUrl(sample.thumbnail_path)
          // The sharper on-demand render only applies to the tilt-series
          // thumbnail; the OVITO preview just enlarges itself in the lightbox.
          const lightboxSrc = !showMd && firstWithTs && tsId
            ? tiltSeriesPreviewUrl(sample.sample_id, firstWithTs.acquisition_id, tsId)
            : null
          const caption = showMd
            ? 'OVITO preview of the MD simulation'
            : 'Middle image of the representative tilt series'
          return (
            <Box>
              <PreviewThumbnail
                src={src}
                lightboxSrc={lightboxSrc}
                alt={
                  showMd
                    ? `OVITO preview for ${sample.sample_id}`
                    : `Middle tilt-series image for ${sample.sample_id}`
                }
                width="100%"
                aspectRatio={1}
                objectFit="contain"
                elevated={false}
                clickable
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: 'block' }}>
                {caption}
              </Typography>
            </Box>
          )
        })()}
        details={
          <FileglancerPathSection path={samplePath}>
            <Stack spacing={2}>
              <SampleContentsCard sample={sample} />
              <EntityFreshnessCard status={sample.scan_status} kind="sample" />
            </Stack>
          </FileglancerPathSection>
        }
      />

      <Divider />

      {/* ── Acquisitions ───────────────────────────────────────────── */}
      <Box>
        <SectionHeading>
          Acquisitions ({sample.acquisitions.length.toLocaleString()})
        </SectionHeading>
        <SampleAcquisitionsTable
          sampleId={sampleId}
          acquisitions={sample.acquisitions}
        />
      </Box>

      <MetadataDrawer
        open={metadataOpen}
        onClose={() => setMetadataOpen(false)}
        eyebrow="Sample details"
        title={sampleId}
      >
        <MetadataSectionList sections={sampleMetadataSections(sample)} />
      </MetadataDrawer>
    </Stack>
  )
}
