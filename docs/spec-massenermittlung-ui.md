# UI Spec — Massenermittlung Results View

Scope: redesign of `public/js/planview.js` viewer + the "Räume" tab in `public/projekt.html`. Must surface confidence (text-layer / vision-validated / vision-only) without scaring the user. Designed against existing tokens in `public/css/style.css` (`--primary #1a3a5c`, `--accent #f39301`, `--bg #f5f7fa`).

## 1. Layout

The current two-column viewer (canvas + 360px sidebar) stays. Three changes:

1. A **trust bar** is inserted between `.plan-viewer-header` and `.plan-viewer-body` (full width, 56px tall).
2. The sidebar widens to **400px** and gains a sticky filter strip at the top.
3. A **detail drawer** slides in from the right (440px) over the canvas when a room is selected — does not replace the sidebar.

```
+--------------------------------------------------------------------------+
| Planansicht           [+ - Anpassen]  [Maße][Räume][Fenster]        [x] |
+--------------------------------------------------------------------------+
| TRUST BAR  42 Räume   38 byte-exakt   3 verifiziert   1 zu prüfen  [Alle]|
+----------------------------------------------------+---------------------+
|                                                    | [Filter: alle ▾]    |
|                                                    | [Top 1  4 Räume ▾]  |
|         PDF CANVAS  +  overlays                    |  ┌──────────────┐   |
|         (rooms outlined per confidence color)      |  │ ● Wohnküche  │   |
|                                                    |  │ 28,45 m² · ...│  |
|         [active room → detail drawer slides in]    |  └──────────────┘   |
|                                                    |  ...                |
+----------------------------------------------------+---------------------+
```

## 2. Room card design (sidebar row)

Card: 12px padding, 8px radius, 1px border `#e5e9f0`, 8px gap between cards. Replaces the current `.pv-room` block.

Line 1 — **source dot** (8px circle, left) + **room name** (15px, 600, `#1a3a5c`) + **Top-badge** (right, 11px uppercase pill `#eef2f7` text `#6c757d`).
Line 2 — three KPI chips, 13px tabular-nums: `28,45 m²`, `U 21,3 m`, `H 2,55 m`. Chip bg `#f5f7fa`, 6px radius, 2/8px padding.
Line 3 — **Bodenbelag**: small icon (12px) + label 12px `#6c757d`, e.g. `Parkett · Eiche`.

### Source dot — single source of truth for confidence
| Source | Dot color | Label (tooltip) |
|---|---|---|
| `text-layer` (byte-exact) | `#16a34a` solid | "Aus PDF-Text · 100 %" |
| `vision-validated` | `#1a3a5c` solid | "KI + Text bestätigt · ~95 %" |
| `vision-only` | `#f39301` ring (hollow, 2px) | "Nur Bilderkennung · prüfen" |
| `manual override` | `#6366f1` solid with white pen glyph | "Manuell korrigiert" |

Active card: 2px left border `--primary`, bg `#f8fafc`. Hover: bg `#f5f7fa`. The card never shows a percentage — only the dot. Power users see the percentage in the drawer.

## 3. Plan overlay (canvas)

Replaces the dashed `rgba(26,58,92,0.4)` cluster outline in `drawOverlays()`. Each room cluster gets a **filled bounding box** colored by source:

| Source | Stroke | Fill | Width |
|---|---|---|---|
| text-layer | `#16a34a` | `rgba(22,163,74,0.08)` | 1.5px solid |
| vision-validated | `#1a3a5c` | `rgba(26,58,92,0.08)` | 1.5px solid |
| vision-only | `#f39301` | `rgba(243,147,1,0.14)` | 2px **dashed [6,4]** |

Active room: stroke 3px, fill alpha doubled, plus a label pill anchored top-left of bbox: white bg, 11px bold, contains room name + area only. No legend changes — the existing `.plan-viewer-legend` is replaced with a "Quelle" legend mirroring the three states above.

## 4. Trust bar (summary header)

56px tall, full width, bg `#ffffff`, bottom border 1px `#e5e9f0`. Left-aligned counters separated by 16px:

`42 Räume erkannt` (15px, 600, `#1a3a5c`)  ·  `● 38 byte-exakt` (`#16a34a`)  ·  `● 3 verifiziert` (`#1a3a5c`)  ·  `● 1 zu prüfen` (`#f39301`, **bold**, clickable → filters sidebar to flagged only).

Right side: `[Alle freigeben]` button (`btn btn-outline`, only enabled when 0 flagged) and `[Excel Export]` (`btn btn-accent`).

## 5. Interactions

- **Hover row** → overlay box pulses (alpha 0.08 → 0.18 over 200ms).
- **Click row** → canvas pans + zooms to bbox (animate 300ms ease-out, target zoom = bbox fits in 60 % of viewport), opens **detail drawer**.
- **Click overlay box** → same as click row, scrolls sidebar to card.
- **Detail drawer** (440px, slides from right, shadow `0 8px 24px rgba(0,0,0,0.12)`): shows the four fields as editable inputs (F, U, H, Bodenbelag dropdown), the source label with confidence %, a thumbnail crop of the bbox from the PDF, and three actions: `Übernehmen` (primary), `Wert ändern` (turns inputs editable; on save → POST `/elemente/:id`, source flips to `manual override`), `Aus Plan entfernen` (danger, secondary).
- **Bulk action**: trust-bar `[Alle freigeben]` flips every `vision-only` room to `vision-validated` after a confirm dialog citing count.

## 6. Filter / sort

Sticky strip in sidebar (40px tall, `#f8fafc` bg):

- **Quelle** segmented control: `Alle` · `Text` · `KI` · `Prüfen` (default `Alle`; counts in subscript).
- **Wohnung** dropdown: populated from `daten.wohnung` values.
- **Bodenbelag** dropdown: aggregated distinct values.
- **Sortierung** dropdown: `Wohnung → Raumname` (default), `Fläche absteigend`, `Konfidenz aufsteigend`.

Filters compose with AND. Filter state persisted in URL hash so a colleague link reopens the same view.

## 7. Edge cases

- **0 rooms**: full-bleed empty state in sidebar — icon (door, 48px, `#cbd5e1`), headline `Keine Räume erkannt` (16px), body `Plan war vermutlich kein Wohnungsgrundriss. Manuell hinzufügen?` and a `[Raum hinzufügen]` outline button. Trust bar collapses to single line "Analyse ohne Treffer".
- **100 % byte-exact**: trust bar shows a green check pill `Alle Werte byte-exakt aus PDF-Text — keine Prüfung nötig` and hides the `[Alle freigeben]` button. Source dots still render (consistency), drawer hides confidence %.
- **All vision-only**: trust bar turns amber bg `#fff7ed`, prepends warning glyph and copy `Diese Datei hat keine Text-Ebene. Bitte alle Räume prüfen.`; detail drawer auto-opens for first flagged room; the `[Alle freigeben]` button is replaced by a disabled-until-reviewed `[Alle freigeben]` (enables once each row was opened at least once — tracked client-side).
