# HA App Kit

Shared libraries for Home Assistant apps: the common web UI and native companion
repair helpers. The UI supplies the app shell, navigation, controls, status
messages, and themes. App data, provider clients, and database migrations stay
in their owning apps.

## Develop

```sh
nix develop
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm storybook
```

Storybook runs the same components shipped in the apps. Run `pnpm check` for
type checks, browser tests, and the production Storybook build.

## Use

`packages/ui` is both a JavaScript package and a small Rust crate. Rust apps
embed its assets at build time, so installed apps need neither Node nor a CDN.
Consumers pin a toolkit release and keep their own release schedule.

Serve `ha_app_ui::SCRIPT` as `app-kit.js` and `ha_app_ui::STYLESHEET` as
`app-kit.css` through the app's existing web listener and ingress checks. The
JavaScript module exports `mountAppShell`, `mountNavigation`, and `setNotice`.
Branding, view routes, actions, and application data stay local.

The shell returns its version and status nodes; it does not assign global IDs.
`setStatus(text, kind)` distinguishes healthy, stale, and failed observations.
Notices use a persistent polite live region. Blocking errors belong in a
separate app-owned alert. Icon URLs are relative or HTTP(S); app-owned inline
SVG belongs in `brand`.

Long native dialogs can use `dialog-panel`, with a form containing
`dialog-heading`, `dialog-body`, and `dialog-footer`. Only the body scrolls; an
`actions` group in the footer wraps its buttons on narrow screens. The app still
owns content spacing, submission, dismissal, focus, and pending work.

Other shared Rust, Python, Nix, and workflow code belongs here when existing
apps demonstrate a common contract. There is no shared application database or
universal domain model.

[`packages/ha`](packages/ha/README.md) supplies the version-repair flow and a
build-time bundler for each companion's private helper package. It uses native
HA backups and update entities, with matching release readbacks before restart.
