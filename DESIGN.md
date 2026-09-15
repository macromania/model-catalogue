# Model catalogue design

## Direction

Low-fidelity product UI. A developer reads and compares dense specifications on a laptop in a bright workspace. Use a light, white surface, dark text, restrained rules, native controls and a single subdued focus/selection accent. No imagery or generated mockups are required.

## Tokens

Use semantic `--cp-*` CSS variables in OKLCH. The Impeccable seed is hue 294.3; its use is limited to focus and selected controls. Neutral backgrounds have zero chroma. Text must meet 4.5:1 contrast; primary ink exceeds 7:1 on white.

Use Segoe UI, Aptos, Calibri and platform sans fallbacks. Use monospace only for IDs, commands and raw data. Body text is 1rem; supporting labels 0.875rem; section headings 1.25rem; page heading 1.5rem. Numeric tables use tabular numerals.

## Layout and components

One top bar, a filter form, a results table, and a separate detail surface with a back link. Comparison is an inline table, not a modal. Use 4, 8, 12, 16, 24, 32 and 48px spacing. Keep prose below 72ch. Tables may scroll inside a labeled, focusable region on narrow screens.

Controls have consistent 4px radii, generous hit areas, and default, hover, focus, disabled and error states. This intentionally overrides decorative artifact defaults to preserve the requested plain UI.

## States

Show loading placeholders, an explicit unseeded database message, distinct no-results and request-failure messages, and unknown values as "Not reported". Azure provider listings do not imply a successful live Azure check.

Motion is limited to short control-state transitions and is disabled for reduced-motion users.
