import { useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  AppBar,
  Box,
  Button,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Typography,
  css,
  styled
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import EditNoteIcon from '@mui/icons-material/EditNote';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import HistoryIcon from '@mui/icons-material/History';
import { CustomLink } from './CustomLink';
import snowflakeLogo from '~/assets/snowflake-logo.svg';

const StyledCustomLink = styled(CustomLink)(
  ({ theme }) => css`
    color: ${theme.palette.common.white};
    font-weight: 500;
  `
);

// The app name doubles as a "home" link, so style it like a heading but keep
// it a link for affordance + keyboard access.
const BrandLink = styled(CustomLink)(
  ({ theme }) => css`
    color: ${theme.palette.secondary.main};
    text-decoration: none;
    font-weight: 700;
  `
);

// Links inside the mobile menu fill the whole MenuItem so the entire row is a
// click target, and inherit the menu's text color rather than link blue.
const MenuLink = styled(CustomLink)`
  display: block;
  width: 100%;
  color: inherit;
  text-decoration: none;
`;

// The desktop "Data management" trigger reads like the plain nav links
// beside it, not a Material button (no chrome, no uppercase transform).
const NavMenuButton = styled(Button)(
  ({ theme }) => css`
    color: ${theme.palette.common.white};
    font-weight: 500;
    text-transform: none;
    font-size: 1rem;
    padding: 0;
    min-width: 0;
  `
);

const DATA_MANAGEMENT_LINKS = [
  {
    to: '/manage/data-organization' as const,
    label: 'Data organization',
    icon: <AccountTreeIcon fontSize="small" />
  },
  {
    to: '/manage/author' as const,
    label: 'Author metadata',
    icon: <EditNoteIcon fontSize="small" />
  },
  {
    to: '/manage/warnings' as const,
    label: 'Review warnings and errors',
    icon: <ReportProblemIcon fontSize="small" />
  },
  {
    to: '/manage/deletions' as const,
    label: 'View deletions and renames',
    icon: <HistoryIcon fontSize="small" />
  }
];

// The mobile nav lives in its own component so Header's JSX stays under the
// max-depth limit; "Data management" expands inline as an accordion rather
// than opening a second menu layer.
function MobileNavMenu({
  anchorEl,
  open,
  onClose
}: {
  readonly anchorEl: HTMLElement | null;
  readonly open: boolean;
  readonly onClose: () => void;
}) {
  return (
    <Menu
      anchorEl={anchorEl}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      id="nav-menu"
      onClose={onClose}
      open={open}
      transformOrigin={{ vertical: 'top', horizontal: 'right' }}
    >
      <MenuItem onClick={onClose}>
        <MenuLink to="/data">All Data</MenuLink>
      </MenuItem>
      <MenuItem onClick={onClose}>
        <MenuLink to="/experimental">Experimental Data</MenuLink>
      </MenuItem>
      <MenuItem onClick={onClose}>
        <MenuLink to="/md-simulation">MD Simulations</MenuLink>
      </MenuItem>
      <Accordion
        disableGutters
        elevation={0}
        square
        sx={{ '&:before': { display: 'none' } }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {/* AccordionSummary doesn't inject MenuItem's body1 typography,
              so match it explicitly to keep the row's text the same
              size as its sibling nav links. */}
          <Typography variant="body1">Data management</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ p: 0 }}>
          <Stack>
            {DATA_MANAGEMENT_LINKS.map(link => (
              <MenuItem key={link.to} onClick={onClose} sx={{ pl: 4 }}>
                <ListItemIcon>{link.icon}</ListItemIcon>
                <MenuLink to={link.to}>{link.label}</MenuLink>
              </MenuItem>
            ))}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Menu>
  );
}

export function Header() {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const menuOpen = Boolean(anchorEl);
  const closeMenu = () => setAnchorEl(null);

  const [dmAnchorEl, setDmAnchorEl] = useState<HTMLElement | null>(null);
  const dmOpen = Boolean(dmAnchorEl);
  const closeDm = () => setDmAnchorEl(null);

  return (
    <Box>
      <AppBar position="static">
        <Toolbar sx={{ gap: 3 }}>
          <BrandLink
            sx={{ display: 'flex', alignItems: 'center', gap: 1 }}
            to="/"
          >
            <Box
              alt=""
              component="img"
              src={snowflakeLogo}
              sx={{ width: 36, height: 36, display: 'block' }}
            />
            <Typography color="inherit" component="span" variant="h6">
              AI+CryoET Data Portal
            </Typography>
          </BrandLink>
          <Box sx={{ flexGrow: 1 }} />

          {/* Desktop / tablet: inline links, "Data management" opens a dropdown. */}
          <Box
            sx={{
              display: { xs: 'none', md: 'flex' },
              gap: 3,
              alignItems: 'center'
            }}
          >
            <StyledCustomLink to="/data">All Data</StyledCustomLink>
            <StyledCustomLink to="/experimental">
              Experimental Data
            </StyledCustomLink>
            <StyledCustomLink to="/md-simulation">
              MD Simulations
            </StyledCustomLink>
            <NavMenuButton
              aria-controls={dmOpen ? 'data-management-menu' : undefined}
              aria-expanded={dmOpen ? 'true' : undefined}
              aria-haspopup="true"
              endIcon={<ArrowDropDownIcon />}
              id="data-management-button"
              onClick={e => setDmAnchorEl(e.currentTarget)}
            >
              Data management
            </NavMenuButton>
            <Menu
              MenuListProps={{ 'aria-labelledby': 'data-management-button' }}
              anchorEl={dmAnchorEl}
              id="data-management-menu"
              onClose={closeDm}
              open={dmOpen}
            >
              {DATA_MANAGEMENT_LINKS.map(link => (
                <MenuItem key={link.to} onClick={closeDm}>
                  <ListItemIcon>{link.icon}</ListItemIcon>
                  <MenuLink to={link.to}>{link.label}</MenuLink>
                </MenuItem>
              ))}
            </Menu>
          </Box>

          {/* Mobile: collapse the links into a hamburger menu; "Data
              management" expands inline as an accordion rather than
              navigating, so its sublinks stay reachable without a second
              menu layer. */}
          <Box sx={{ display: { xs: 'flex', md: 'none' } }}>
            <IconButton
              aria-controls={menuOpen ? 'nav-menu' : undefined}
              aria-expanded={menuOpen ? 'true' : undefined}
              aria-haspopup="true"
              aria-label="Open navigation menu"
              color="inherit"
              edge="end"
              onClick={e => setAnchorEl(e.currentTarget)}
            >
              <MenuIcon />
            </IconButton>
            <MobileNavMenu
              anchorEl={anchorEl}
              onClose={closeMenu}
              open={menuOpen}
            />
          </Box>
        </Toolbar>
      </AppBar>
    </Box>
  );
}
