# Design tokens

Single source of truth for ClawCast palette, spacing, and radii. Edit
`tokens.json`, run `npm run build`, commit the regenerated outputs.

## Outputs

- **iOS** — `../ios/NewsletterPodApp/DesignTokens.swift` (consumed by `Theme.swift`).
- **Web** — `dist/tokens.css` (consumed by the marketing site once it exists).

Both generated files are committed so neither platform needs Node to build.

## Usage

```sh
cd design-tokens
npm install   # first time only
npm run build
```

## Adding a new token

1. Add it to `tokens.json` under the right category (`color`, `spacing`, `radius`).
2. `npm run build`.
3. In Swift, reference it as `DesignTokens.<category><Name>`
   (e.g. `DesignTokens.colorAmber`). In CSS, use `var(--<category>-<name>)`.
4. Commit `tokens.json` plus both generated files together so iOS/web
   stay in sync.
