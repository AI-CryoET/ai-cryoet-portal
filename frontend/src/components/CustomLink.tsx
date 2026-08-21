import React from 'react';
import { createLink } from '@tanstack/react-router';
import { Button, IconButton, Link } from '@mui/material';
import type { ButtonProps, IconButtonProps, LinkProps } from '@mui/material';
import type { LinkComponent } from '@tanstack/react-router';

type MUILinkProps = LinkProps;

const MUILinkComponent = React.forwardRef<HTMLAnchorElement, MUILinkProps>(
  (props, ref) => <Link ref={ref} {...props} />
);
MUILinkComponent.displayName = 'MUILinkComponent';

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
MUIButtonLinkComponent.displayName = 'MUIButtonLinkComponent';

const CreatedButtonLink = createLink(MUIButtonLinkComponent);

export const ButtonLink: LinkComponent<
  typeof MUIButtonLinkComponent
> = props => {
  return <CreatedButtonLink preload="intent" {...props} />;
};

// Same as `ButtonLink`, but for an icon-only action (e.g. "edit" next to a
// name) — renders as a real anchor rather than a `<button>` nested inside one.
type MUIIconButtonLinkProps = IconButtonProps<'a'>;

const MUIIconButtonLinkComponent = React.forwardRef<
  HTMLAnchorElement,
  MUIIconButtonLinkProps
>((props, ref) => <IconButton ref={ref} {...props} component="a" />);
MUIIconButtonLinkComponent.displayName = 'MUIIconButtonLinkComponent';

const CreatedIconButtonLink = createLink(MUIIconButtonLinkComponent);

export const IconButtonLink: LinkComponent<
  typeof MUIIconButtonLinkComponent
> = props => {
  return <CreatedIconButtonLink preload="intent" {...props} />;
};
