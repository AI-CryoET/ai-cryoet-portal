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
} from '~/utils/queryOptions'

// Free-text search carried in the URL (e.g. /manage/warnings?q=villa_004 from a
// detail page's "view metadata errors" link, or typed into the search box).
type ManageSearch = { q?: string }

export const Route = createFileRoute('/manage/warnings')({
  validateSearch: (search: Record<string, unknown>): ManageSearch => ({
    q: typeof search.q === 'string' && search.q ? search.q : undefined,
  }),
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps }) =>
    Promise.all([
      queryClient.ensureQueryData(manageSummaryQueryOptions),
      queryClient.ensureQueryData(outstandingIssuesQueryOptions({ q: deps.q })),
      queryClient.ensureQueryData(recentlyResolvedQueryOptions(24)),
    ]),
  component: ManageRoute,
})

function ManageRoute() {
  const { q } = Route.useSearch()
  const navigate = Route.useNavigate()
  const { data: summary } = useManageSummaryQuery()
  const { data: resolved } = useRecentlyResolvedQuery(24)

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
        <OutstandingIssuesTable
          q={q ?? ''}
          onQueryChange={(value) =>
            navigate({
              // replace: typing shouldn't stack a history entry per keystroke.
              search: (prev) => ({ ...prev, q: value || undefined }),
              replace: true,
            })
          }
        />
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
