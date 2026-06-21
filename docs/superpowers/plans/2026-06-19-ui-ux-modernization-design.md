# UI/UX Modernization Specification (2026-06-19)

This spec details the modernization of the Trading Journal application, integrating Light/Dark themes, Glassmorphism aesthetics, compact drawer-based form inputs, and advanced visualization with ApexCharts.

## 1. Architectural Theme Configurations (style.css)

Dynamic theme attributes are defined on `:root` using properties scoped to `[data-theme="dark"]` and `[data-theme="light"]`.

```css
/* Dark Theme (Default) */
:root, :root[data-theme="dark"] {
  --bg: #090e14;
  --surface: rgba(15, 23, 36, 0.6);
  --surface-opaque: #0f1724;
  --surface-soft: #1e293b;
  --text: #f1f5f9;
  --subtle: #94a3b8;
  --line: rgba(148, 163, 184, 0.12);
  --line-strong: rgba(148, 163, 184, 0.25);
  --primary: #38bdf8;
  --primary-ink: #0284c7;
  --accent: #f97316;
  --danger: #ef4444;
  --ok: #10b981;
  --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.32);
  --glass-border: 1px solid rgba(255, 255, 255, 0.08);
}

/* Light Theme */
:root[data-theme="light"] {
  --bg: #f4f4f1;
  --surface: rgba(255, 255, 255, 0.82);
  --surface-opaque: #ffffff;
  --surface-soft: #f0f3f7;
  --text: #14202b;
  --subtle: #5e6b79;
  --line: #d7dfe8;
  --line-strong: #b9c7d6;
  --primary: #1f5473;
  --primary-ink: #0f3145;
  --accent: #c35a32;
  --danger: #9e1f1f;
  --ok: #206245;
  --glass-shadow: 0 8px 24px rgba(20, 32, 43, 0.04);
  --glass-border: 1px solid rgba(20, 32, 43, 0.08);
}
```

* **Body Background Gradient**: Transition effects are specified to prevent jagged style jumps on theme toggling.
* **Glassmorphism Styling**: Applied via `backdrop-filter: blur(12px)` and matching variable border color borders (`var(--glass-border)`) and shadows (`var(--glass-shadow)`).

## 2. Layout Form Modernization (journal.html)

Input forms (BUY, SELL, CASHFLOW, SL_UPDATE) are migrated into sidebar draw-out units (`.drawer`) which are hidden offscreen by default (`right: -420px; transition: transform 0.28s`).
A clean header bar (`.quick-action-bar`) containing buttons toggles drawer active states:

```javascript
function openDrawer(drawerId) {
  closeAllDrawers();
  const drawer = document.getElementById(drawerId);
  const overlay = document.getElementById("drawer-overlay");
  if (drawer && overlay) {
    drawer.classList.add("is-active");
    overlay.classList.add("is-active");
    document.body.style.overflow = "hidden";
  }
}

function closeAllDrawers() {
  document.querySelectorAll(".drawer").forEach((d) => d.classList.remove("is-active"));
  const overlay = document.getElementById("drawer-overlay");
  if (overlay) overlay.classList.remove("is-active");
  document.body.style.overflow = "";
}
```

* **Escape key listener** closes active drawers instantly.
* Page content transitions are optimized so the ledger table takes primary vertical real estate.

## 3. Data Chart Visualization (stats.html)

The legacy, hardcoded SVG builder layout is entirely deprecated. Charts are initialized using `ApexCharts` via script imports.

* **Performance Statistics Graphs**: Rendered as smooth-curve `area` charts, matching dynamic theme styles (text colors, grid line contrast).
* **Mixed Distribution Charts**: Represented using bar histograms overlapped with smooth trend line series.
* **Theme Synchronization**: A dynamic theme observer triggers options updates across initialized charts:
  ```javascript
  window.addEventListener("theme-change", (e) => {
    const nextTheme = e.detail.theme;
    Object.keys(activeCharts).forEach((key) => {
      activeCharts[key].updateOptions({
        theme: { mode: nextTheme },
        // updates grid, legend, and axis styles ...
      });
    });
  });
  ```
