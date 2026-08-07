import { createTheme } from '@mui/material/styles';

// Palette derived from the AI+CryoET snowflake icon:
//   #145266 — dark petrol blue (icon background)
//   #a8d4f0 — icy blue-white (icon nodes/branches)
// See create_ai_cryoet_icon.py / create_ai_cryoet_svg.py.
const PETROL = '#145266';
const ICY = '#a8d4f0';
// A deeper, still-saturated petrol used for `primary.dark` (hero banner, the
// big stat numbers, button text). Chosen explicitly instead of MUI's default
// `darken(main)`, which produced a muddy desaturated tone.
const DEEP_PETROL = '#0e3d4b';

const HEADING_VARIANTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'];

export const theme = createTheme({
  typography: {
    fontFamily: "'Roboto Variable', sans-serif"
  },
  palette: {
    primary: {
      main: PETROL,
      dark: DEEP_PETROL,
      contrastText: '#ffffff'
    },
    secondary: {
      main: ICY,
      // Icy blue is light, so dark petrol reads better than white on top of it.
      contrastText: PETROL
    }
  },
  components: {
    MuiTypography: {
      styleOverrides: {
        // Page headings render in petrol instead of the default near-black.
        // Only applies to heading variants that don't set an explicit `color`,
        // so headings on dark surfaces (navbar, hero) — which pass
        // `color="inherit"` — keep inheriting white from their container.
        root: ({ ownerState }) => ({
          ...(ownerState.variant &&
            HEADING_VARIANTS.includes(ownerState.variant) &&
            ownerState.color == null && {
              color: PETROL
            })
        })
      }
    }
  }
});
