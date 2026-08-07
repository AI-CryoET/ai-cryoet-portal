import { Chip, Typography } from '@mui/material';

// Acquisition quality is a researcher-authored integer rating, 1 (worst) to 5
// (best). Map it to a traffic-light palette so it's scannable at a glance:
// green for good, amber for middling, red for poor.
function qualityColor(q: number): { bg: string; fg: string } {
  if (q >= 4) {
    return { bg: 'success.main', fg: 'success.contrastText' };
  }
  if (q === 3) {
    return { bg: 'warning.main', fg: 'warning.contrastText' };
  }
  return { bg: 'error.main', fg: 'error.contrastText' };
}

// A colored badge for an acquisition's quality rating. Renders the same "—"
// placeholder the metadata views use when the rating is missing, so empty
// cells stay aligned with the rest of the table.
export function QualityBadge({
  quality
}: {
  readonly quality: number | null | undefined;
}) {
  if (quality == null) {
    return (
      <Typography color="text.disabled" component="span" variant="body2">
        —
      </Typography>
    );
  }
  const { bg, fg } = qualityColor(quality);
  return (
    <Chip
      label={`${quality} / 5`}
      size="small"
      sx={{ bgcolor: bg, color: fg, fontWeight: 600 }}
    />
  );
}
