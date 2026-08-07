import { Box, Grid, Paper, Typography } from '@mui/material';
import type { StatsOverviewOut } from '~/types';

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function BannerStatCard({
  label,
  value
}: {
  readonly label: string;
  readonly value: string | number;
}) {
  return (
    <Paper
      elevation={0}
      sx={{
        px: 2.5,
        py: 1.75,
        minWidth: 150,
        borderRadius: 2,
        height: '100%',
        border: 1,
        borderColor: 'divider'
      }}
    >
      <Typography color="text.secondary" gutterBottom variant="body2">
        {label}
      </Typography>
      <Typography color="primary.dark" component="div" variant="h4">
        {value}
      </Typography>
    </Paper>
  );
}

// "Data at a glance" — the high-level totals researchers check regularly. Lives
// on the landing page below the hero (moved off the browse/experimental page).
export function StatsBanner({ stats }: { readonly stats: StatsOverviewOut }) {
  const { totals, by_project } = stats;
  const totalBytes = by_project.reduce(
    (sum, p) => sum + (p.size_bytes ?? 0),
    0
  );

  const cards = [
    { label: 'Total data', value: formatBytes(totalBytes) },
    { label: 'Samples', value: totals.samples.toLocaleString() },
    { label: 'Acquisitions', value: totals.acquisitions.toLocaleString() },
    { label: 'Tomograms', value: totals.tomograms.toLocaleString() }
  ];

  return (
    <Box>
      <Typography gutterBottom variant="h6">
        Data at a glance
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }} variant="body2">
        High-level stats of interest on a regular basis.
      </Typography>
      <Grid container spacing={2}>
        {cards.map(c => (
          <Grid item key={c.label} sm={3} xs={6}>
            <BannerStatCard label={c.label} value={c.value} />
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
