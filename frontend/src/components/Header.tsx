import { useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  AppBar,
  Box,
  Button,
  IconButton,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Typography,
  css,
  styled,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ArrowDropDownIcon from "@mui/icons-material/ArrowDropDown";
import { CustomLink } from "./CustomLink";
import snowflakeLogo from "~/assets/snowflake-logo.svg";

const StyledCustomLink = styled(CustomLink)(
  ({ theme }) => css`
    color: ${theme.palette.common.white};
    font-weight: 500;
  `,
);

// The app name doubles as a "home" link, so style it like a heading but keep
// it a link for affordance + keyboard access.
const BrandLink = styled(CustomLink)(
  ({ theme }) => css`
    color: ${theme.palette.secondary.main};
    text-decoration: none;
    font-weight: 700;
  `,
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
  `,
);

const DATA_MANAGEMENT_LINKS = [
  { to: "/manage/data-organization" as const, label: "Data organization" },
  { to: "/manage/author" as const, label: "Author metadata" },
  { to: "/manage" as const, label: "Review warnings and errors" },
  { to: "/manage/deletions" as const, label: "View deletions and renames" },
];

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
            to="/"
            sx={{ display: "flex", alignItems: "center", gap: 1 }}
          >
            <Box
              component="img"
              src={snowflakeLogo}
              alt=""
              sx={{ width: 36, height: 36, display: "block" }}
            />
            <Typography variant="h6" component="span" color="inherit">
              AI+CryoET Data Portal
            </Typography>
          </BrandLink>
          <Box sx={{ flexGrow: 1 }} />

          {/* Desktop / tablet: inline links, "Data management" opens a dropdown. */}
          <Box sx={{ display: { xs: "none", md: "flex" }, gap: 3, alignItems: "center" }}>
            <StyledCustomLink to="/data">All Data</StyledCustomLink>
            <StyledCustomLink to="/experimental">
              Experimental Data
            </StyledCustomLink>
            <StyledCustomLink to="/md-simulation">
              MD Simulations
            </StyledCustomLink>
            <NavMenuButton
              id="data-management-button"
              aria-controls={dmOpen ? "data-management-menu" : undefined}
              aria-haspopup="true"
              aria-expanded={dmOpen ? "true" : undefined}
              onClick={(e) => setDmAnchorEl(e.currentTarget)}
              endIcon={<ArrowDropDownIcon />}
            >
              Data management
            </NavMenuButton>
            <Menu
              id="data-management-menu"
              anchorEl={dmAnchorEl}
              open={dmOpen}
              onClose={closeDm}
              MenuListProps={{ "aria-labelledby": "data-management-button" }}
            >
              {DATA_MANAGEMENT_LINKS.map((link) => (
                <MenuItem key={link.to} onClick={closeDm}>
                  <MenuLink to={link.to}>{link.label}</MenuLink>
                </MenuItem>
              ))}
            </Menu>
          </Box>

          {/* Mobile: collapse the links into a hamburger menu; "Data
              management" expands inline as an accordion rather than
              navigating, so its sublinks stay reachable without a second
              menu layer. */}
          <Box sx={{ display: { xs: "flex", md: "none" } }}>
            <IconButton
              color="inherit"
              edge="end"
              aria-label="Open navigation menu"
              aria-controls={menuOpen ? "nav-menu" : undefined}
              aria-haspopup="true"
              aria-expanded={menuOpen ? "true" : undefined}
              onClick={(e) => setAnchorEl(e.currentTarget)}
            >
              <MenuIcon />
            </IconButton>
            <Menu
              id="nav-menu"
              anchorEl={anchorEl}
              open={menuOpen}
              onClose={closeMenu}
              anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
              transformOrigin={{ vertical: "top", horizontal: "right" }}
            >
              <MenuItem onClick={closeMenu}>
                <MenuLink to="/data">All Data</MenuLink>
              </MenuItem>
              <MenuItem onClick={closeMenu}>
                <MenuLink to="/experimental">Experimental Data</MenuLink>
              </MenuItem>
              <MenuItem onClick={closeMenu}>
                <MenuLink to="/md-simulation">MD Simulations</MenuLink>
              </MenuItem>
              <Accordion
                disableGutters
                elevation={0}
                square
                sx={{ "&:before": { display: "none" } }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  {/* AccordionSummary doesn't inject MenuItem's body1 typography,
                      so match it explicitly to keep the row's text the same
                      size as its sibling nav links. */}
                  <Typography variant="body1">Data management</Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ p: 0 }}>
                  <Stack>
                    {DATA_MANAGEMENT_LINKS.map((link) => (
                      <MenuItem key={link.to} onClick={closeMenu} sx={{ pl: 4 }}>
                        <MenuLink to={link.to}>{link.label}</MenuLink>
                      </MenuItem>
                    ))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
            </Menu>
          </Box>
        </Toolbar>
      </AppBar>
    </Box>
  );
}
