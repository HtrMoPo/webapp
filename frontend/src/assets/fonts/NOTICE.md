Fonts in this directory are third-party, both licensed under the SIL Open
Font License 1.1 (full text alongside each family as `OFL.txt`).

- `junicode/` -- Junicode 2.226, by Peter S. Baker.
  https://github.com/psb1558/Junicode-font
- `scheherazade/` -- Scheherazade New 4.500, by SIL International.
  https://github.com/silnrsi/font-scheherazade

Both are specialist fonts used by the playground's recognized-text
renderer (Junicode for Latin/medieval scripts, Scheherazade New for
Arabic) and are self-hosted here via `@font-face` in
`src/styles/main.css` so they render regardless of what the reader has
installed system-wide.
