# Beautiful UI components

Source: https://github.com/slev12397/beautiful-ui
Catalogue: https://www.beautifului.dev/
License: MIT, copyright 2026 Shane Levine. Full notice: `../BEAUTIFUL-UI-LICENSE`.

- `SidebarNav.tsx`: adapted from upstream `components/primitives/SidebarNav.tsx`; retains collapse, search, and gliding navigation. Inline icons replace the upstream icon dependency. Workspace naming, real session history, and disabled controls are application integrations.
- `PromptBar.tsx`: adapted from upstream `components/primitives/PromptBar.tsx`. Live mode disables demo animations and hides unsupported source/model/dictation actions. Adds initial drafts and sending state.
- `primitives/GlideMenu.tsx`: upstream hover and focus highlight primitive.
- `app/globals.css`: includes upstream sidebar transition rules and the control/chip/card radius scale, mapped to the application's shadcn neutral tokens.

The chat uses the existing shadcn Button and Radix-backed Dialog. On mobile, navigation is a focus-trapped dialog. No new runtime dependencies are required.
