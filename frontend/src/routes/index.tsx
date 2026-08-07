import { createFileRoute } from '@tanstack/react-router';
import { Stack } from '@mui/material';
import {
  samplesQueryOptions,
  statsOverviewQueryOptions,
  useSamplesQuery,
  useStatsOverviewQuery
} from '~/utils/queryOptions';
import { StatsBanner } from '~/components/landing/StatsBanner';
import { CoverageSummary } from '~/components/landing/CoverageSummary';

export const Route = createFileRoute('/')({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(statsOverviewQueryOptions),
      // Coverage cross-tabulates the full data set (no filters on the landing
      // page), so prime the unfiltered samples list.
      queryClient.ensureQueryData(samplesQueryOptions())
    ]),
  component: Landing
});

function Landing() {
  const { data: stats } = useStatsOverviewQuery();
  const { data: samples } = useSamplesQuery();
  const rows = samples ?? [];

  return (
    // The root layout caps content at `xl` on wide screens; the landing page
    // reads better narrower, so cap it at `lg` and center it.
    <Stack
      spacing={4}
      sx={theme => ({
        width: '100%',
        maxWidth: theme.breakpoints.values.lg,
        mx: 'auto'
      })}
    >
      <StatsBanner stats={stats} />
      <CoverageSummary rows={rows} />
    </Stack>
  );
}
