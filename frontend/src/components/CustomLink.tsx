import React from 'react';
import { createLink } from '@tanstack/react-router';
import { Button, Link } from '@mui/material';
import type { ButtonProps, LinkProps } from '@mui/material';
import type { LinkComponent } from '@tanstack/react-router';

type MUILinkProps = LinkProps;

const MUILinkComponent = React.forwardRef<HTMLAnchorElement, MUILinkProps>(
  (props, ref) => <Link ref={ref} {...props} />
);

const CreatedLinkComponent = createLink(MUILinkComponent);

export const CustomLink: LinkComponent<typeof MUILinkComponent> = props => {
  return <CreatedLinkComponent preload="intent" {...props} />;
};

// `ButtonProps<'a'>` types the Button for an anchor root, matching the
// `component="a"` below so the router can drive it as a link while keeping
// button styling.
type MUIButtonLinkProps = ButtonProps<'a'>;

const MUIButtonLinkComponent = React.forwardRef<
  HTMLAnchorElement,
  MUIButtonLinkProps
>((props, ref) => <Button ref={ref} {...props} component="a" />);

const CreatedButtonLink = createLink(MUIButtonLinkComponent);

export const ButtonLink: LinkComponent<
  typeof MUIButtonLinkComponent
> = props => {
  return <CreatedButtonLink preload="intent" {...props} />;
};
