/// <reference types="vite/client" />
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools';
import {
  HeadContent,
  Outlet,
  Scripts,
  createRootRouteWithContext,
  useRouterState
} from '@tanstack/react-router';
import { CacheProvider } from '@emotion/react';
import { Box, Container, CssBaseline, ThemeProvider } from '@mui/material';
import createCache from '@emotion/cache';
import { QueryClientProvider } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import fontsourceVariableRobotoCss from '@fontsource-variable/roboto?url';
import React from 'react';
import { theme } from '~/styles/theme';
import { Header } from '~/components/Header';
import { Footer } from '~/components/Footer';
import { LandingHero } from '~/components/landing/LandingHero';

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()(
  {
    head: () => ({
      links: [
        { rel: 'stylesheet', href: fontsourceVariableRobotoCss },
        // Snowflake icon (served from frontend/public). SVG for modern browsers,
        // .ico fallback, and apple-touch-icon for iOS home-screen shortcuts.
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' }
      ]
    }),
    component: RootComponent
  }
);

function RootComponent() {
  return (
    <RootDocument>
      <Outlet />
    </RootDocument>
  );
}

function Providers({ children }: { readonly children: React.ReactNode }) {
  const { queryClient } = Route.useRouteContext();
  const [emotionCache] = React.useState(() => createCache({ key: 'css' }));

  return (
    <CacheProvider value={emotionCache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </ThemeProvider>
    </CacheProvider>
  );
}

function RootDocument({ children }: { readonly children: React.ReactNode }) {
  const pathname = useRouterState({ select: s => s.location.pathname });
  // The landing hero is a full-bleed banner, so it renders as a direct sibling
  // of <Header> — outside the centered, max-width <Container> below — letting
  // it span the viewport and sit flush under the nav.
  const isLanding = pathname === '/';

  return (
    <html>
      <head>
        <HeadContent />
      </head>
      <body>
        <Providers>
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              minHeight: '100vh'
            }}
          >
            <Header />
            {isLanding ? <LandingHero /> : null}
            {/*
              Fluid below `lg`, capped at the `lg` width through the `lg`
              range so laptops keep comfortable margins, then expanding to the
              `xl` width on large monitors to give the tables room.
            */}
            <Container
              component="main"
              maxWidth={false}
              sx={theme => ({
                paddingBlock: 4,
                flex: 1,
                mx: 'auto',
                maxWidth: {
                  lg: theme.breakpoints.values.lg,
                  xl: theme.breakpoints.values.xl
                }
              })}
            >
              {children}
            </Container>
            <Footer />
          </Box>
        </Providers>

        <TanStackRouterDevtools position="bottom-right" />
        <Scripts />
      </body>
    </html>
  );
}
