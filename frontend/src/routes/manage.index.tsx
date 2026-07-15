import { createFileRoute } from '@tanstack/react-router'
import {
  Box,
  Breadcrumbs,
  Card,
  CardContent,
  Stack,
  Typography,
} from '@mui/material'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import EditNoteIcon from '@mui/icons-material/EditNote'
import ReportProblemIcon from '@mui/icons-material/ReportProblem'
import HistoryIcon from '@mui/icons-material/History'
import { CustomLink } from '~/components/CustomLink'
import type { LinkProps } from '@tanstack/react-router'

export const Route = createFileRoute('/manage/')({
  component: ManageIndexRoute,
})

// The four data-management destinations, as hub cards. `to` is typed against
// the router so a broken link fails the build.
const CARDS: {
  to: LinkProps['to']
  icon: React.ReactNode
  title: string
  blurb: string
}[] = [
  {
    to: '/manage/data-organization',
    icon: <AccountTreeIcon fontSize="large" color="primary" />,
    title: 'Data organization',
    blurb:
      'How to upload and structure data on the file share, and review the current metadata schema.',
  },
  {
    to: '/manage/author',
    icon: <EditNoteIcon fontSize="large" color="primary" />,
    title: 'Author metadata',
    blurb:
      'Use an online form to author sample.toml, acquisition.toml, and md_run.toml metadata files.',
  },
  {
    to: '/manage/warnings',
    icon: <ReportProblemIcon fontSize="large" color="primary" />,
    title: 'Review warnings and errors',
    blurb:
      'Identify metadata files that need to be edited to match the metadata schema.',
  },
  {
    to: '/manage/deletions',
    icon: <HistoryIcon fontSize="large" color="primary" />,
    title: 'View deletions and renames',
    blurb:
      'See all samples and acquisitions that have been deleted from the data portal.',
  },
]

function ManageIndexRoute() {
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Manage</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Manage data
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Everything for getting cryoET data into the catalog and keeping its
          metadata healthy.
        </Typography>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' },
        }}
      >
        {CARDS.map((card) => (
          <CustomLink
            key={card.to}
            to={card.to}
            underline="none"
            sx={{ display: 'block', height: '100%' }}
          >
            <Card
              variant="outlined"
              sx={{
                height: '100%',
                transition: 'border-color 120ms, box-shadow 120ms',
                '&:hover': { borderColor: 'primary.main', boxShadow: 2 },
              }}
            >
              <CardContent>
                <Stack direction="row" spacing={2} alignItems="flex-start">
                  {card.icon}
                  <Box>
                    <Typography variant="h6" component="h2" color="text.primary">
                      {card.title}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
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
  )
}
