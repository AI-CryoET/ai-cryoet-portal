import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { StatusCadenceCard } from '~/components/manage/StatusCadenceCard'
import { SectionHeader } from '~/components/manage/SectionHeader'
import { OutstandingIssuesTable } from '~/components/manage/OutstandingIssuesTable'
import { RecentlyResolvedTable } from '~/components/manage/RecentlyResolvedTable'
import {
  manageSummaryQueryOptions,
  outstandingIssuesQueryOptions,
  recentlyResolvedQueryOptions,
  useManageSummaryQuery,
  useRecentlyResolvedQuery,
  type IssueFilters,
} from '~/utils/queryOptions'

// Optional entity filter carried in the URL (e.g. /manage/warnings?sample=s1
// from a detail page's "view metadata errors" link).
type ManageSearch = { sample?: string; acquisition?: string }

export const Route = createFileRoute('/manage/warnings')({
  validateSearch: (search: Record<string, unknown>): ManageSearch => ({
    sample: typeof search.sample === 'string' ? search.sample : undefined,
    acquisition:
      typeof search.acquisition === 'string' ? search.acquisition : undefined,
  }),
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps }) =>
    Promise.all([
      queryClient.ensureQueryData(manageSummaryQueryOptions),
      queryClient.ensureQueryData(
        outstandingIssuesQueryOptions({ q: entityQuery(deps) }),
      ),
      queryClient.ensureQueryData(recentlyResolvedQueryOptions(24)),
    ]),
  component: ManageRoute,
})

// Search text seeding the outstanding-issues box from a detail page's "view
// warnings" link: both the sample and acquisition names (space-separated, so
// the backend's all-terms-must-match search narrows to that one acquisition,
// since acquisition ids aren't unique across samples).
function entityQuery({
  sample,
  acquisition,
}: ManageSearch): string | undefined {
  return [sample, acquisition].filter(Boolean).join(' ') || undefined
}

function ManageRoute() {
  const { sample, acquisition } = Route.useSearch()
  const { data: summary } = useManageSummaryQuery()
  const { data: resolved } = useRecentlyResolvedQuery(24)

  const outstandingCount =
    summary.outstanding.errors + summary.outstanding.warnings
  const initialFilters: IssueFilters = { q: entityQuery({ sample, acquisition }) }

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit">
          Manage
        </CustomLink>
        <Typography color="text.primary">Warnings &amp; errors</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Review warnings &amp; errors
        </Typography>
        <Typography variant="body2" color="text.secondary">
          File system scan health, data freshness, and scan logs.
        </Typography>
      </Box>

      <StatusCadenceCard summary={summary} />

      <Box>
        <CustomLink to="/manage/scans" variant="body2">
          View scan history
        </CustomLink>
      </Box>

      <Box>
        <SectionHeader
          count={outstandingCount}
          title="Outstanding data warnings & errors"
        />
        <OutstandingIssuesTable initialFilters={initialFilters} />
      </Box>

      <Box>
        <SectionHeader
          count={resolved.length}
          title="Recently resolved warnings & errors (last 24h)"
        />
        <RecentlyResolvedTable withinHours={24} />
      </Box>
    </Stack>
  )
}
