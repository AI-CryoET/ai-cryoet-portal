import { createFileRoute } from '@tanstack/react-router';
import {
  Box,
  Breadcrumbs,
  Card,
  CardContent,
  Stack,
  Typography
} from '@mui/material';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import EditNoteIcon from '@mui/icons-material/EditNote';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import HistoryIcon from '@mui/icons-material/History';
import { CustomLink } from '~/components/CustomLink';
import type { LinkProps } from '@tanstack/react-router';

export const Route = createFileRoute('/manage/')({
  component: ManageIndexRoute
});

// The four data-management destinations, as hub cards. `to` is typed against
// the router so a broken link fails the build.
const CARDS: {
  to: LinkProps['to'];
  icon: React.ReactNode;
  title: string;
  blurb: string;
}[] = [
  {
    to: '/manage/data-organization',
    icon: <AccountTreeIcon color="primary" fontSize="large" />,
    title: 'Data organization',
    blurb:
      'How to upload and structure data on the file share, and review the current metadata schema.'
  },
  {
    to: '/manage/author',
    icon: <EditNoteIcon color="primary" fontSize="large" />,
    title: 'Author metadata',
    blurb:
      'Use an online form to author sample.toml, acquisition.toml, and md_run.toml metadata files.'
  },
  {
    to: '/manage/warnings',
    icon: <ReportProblemIcon color="primary" fontSize="large" />,
    title: 'Review warnings and errors',
    blurb:
      'Identify metadata files that need to be edited to match the metadata schema.'
  },
  {
    to: '/manage/deletions',
    icon: <HistoryIcon color="primary" fontSize="large" />,
    title: 'View deletions and renames',
    blurb:
      'See all samples and acquisitions that have been deleted from the data portal.'
  }
];

function ManageIndexRoute() {
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink color="inherit" sx={{ fontWeight: 700 }} to="/">
          Home
        </CustomLink>
        <Typography color="text.primary">Manage</Typography>
      </Breadcrumbs>

      <Box>
        <Typography component="h1" variant="h5">
          Manage data
        </Typography>
        <Typography color="text.secondary" variant="body2">
          Everything for getting cryoET data into the catalog and keeping its
          metadata healthy.
        </Typography>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' }
        }}
      >
        {CARDS.map(card => (
          <CustomLink
            key={card.to}
            sx={{ display: 'block', height: '100%' }}
            to={card.to}
            underline="none"
          >
            <Card
              sx={{
                height: '100%',
                transition: 'border-color 120ms, box-shadow 120ms',
                '&:hover': { borderColor: 'primary.main', boxShadow: 2 }
              }}
              variant="outlined"
            >
              <CardContent>
                <Stack alignItems="flex-start" direction="row" spacing={2}>
                  {card.icon}
                  <Box>
                    <Typography
                      color="text.primary"
                      component="h2"
                      variant="h6"
                    >
                      {card.title}
                    </Typography>
                    <Typography color="text.secondary" variant="body2">
                      {card.blurb}
                    </Typography>
                  </Box>
                </Stack>
              </CardContent>
            </Card>
          </CustomLink>
        ))}
      </Box>
    </Stack>
  );
}
