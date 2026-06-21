# UI/UX Edit Drawer Design Plan (2026-06-21)

This spec details the replacement of the native `window.prompt` JSON editor in `journal.html` with a structured, sidebar draw-out unit (`#drawer-edit`) to provide a modern, theme-consistent UI for modifying transaction events.

## 1. Edit Drawer HTML Layout

A new drawer container `#drawer-edit` is placed adjacent to the existing `#drawer-sl` in `journal.html`:

```html
  <!-- EDIT Drawer -->
  <div id="drawer-edit" class="drawer">
    <div class="drawer-header">
      <h3 id="edit-drawer-title">Edit Event</h3>
      <button type="button" class="drawer-close-btn" onclick="closeAllDrawers()">&times;</button>
    </div>
    <form id="edit-event-form">
      <input type="hidden" id="edit-event-id" />
      <input type="hidden" id="edit-event-type" />
      
      <!-- Common Fields -->
      <div class="form-row">
        <div>
          <label>Timestamp</label>
          <input id="edit-ts" name="ts" type="datetime-local" step="1" required />
        </div>
        <div>
          <label>Ticker</label>
          <input id="edit-ticker" name="ticker" placeholder="Ticker" />
        </div>
      </div>
      <div class="form-row">
        <div>
          <label>Market</label>
          <select id="edit-market" name="market">
            <option value="">Market (opt)</option>
            <option value="KR">KR</option>
            <option value="US">US</option>
            <option value="HK">HK</option>
            <option value="JP">JP</option>
          </select>
        </div>
        <div>
          <label>Currency</label>
          <select id="edit-currency" name="currency">
            <option value="">Currency (opt)</option>
            <option value="KRW">KRW</option>
            <option value="USD">USD</option>
            <option value="HKD">HKD</option>
            <option value="JPY">JPY</option>
          </select>
        </div>
        <div>
          <label>FX to Base</label>
          <input id="edit-fx-rate" name="fx_rate_to_base" type="number" step="any" placeholder="1.0" />
        </div>
      </div>

      <!-- BUY / SELL Specific Fields -->
      <div class="form-row" id="edit-buy-sell-fields" style="display:none">
        <div id="edit-qty-wrapper">
          <label>Qty</label>
          <input id="edit-qty" name="qty" type="number" step="any" />
        </div>
        <div>
          <label>Price</label>
          <input id="edit-price" name="price" type="number" step="any" />
        </div>
        <div>
          <label>Fee</label>
          <input id="edit-fee" name="fee" type="number" step="any" />
        </div>
      </div>

      <!-- SL_UPDATE Specific Fields -->
      <div class="form-row" id="edit-sl-fields" style="display:none">
        <div>
          <label>Stop Loss (SL)</label>
          <input id="edit-sl" name="sl" type="number" step="any" />
        </div>
        <div>
          <label>Take Profit (TP)</label>
          <input id="edit-tp" name="tp" type="number" step="any" />
        </div>
      </div>

      <!-- CASHFLOW Specific Fields -->
      <div class="form-row" id="edit-cash-fields" style="display:none">
        <div>
          <label>Cash Amount</label>
          <input id="edit-cash" name="cash_amount" type="number" step="any" />
        </div>
      </div>

      <!-- REVIEW Specific Fields -->
      <div class="form-row" id="edit-review-fields" style="display:none">
        <div style="flex:1">
          <label>Review Text</label>
          <textarea id="edit-review" name="review_text" rows="4" style="width:100%; box-sizing:border-box; background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:8px; color:var(--text)"></textarea>
        </div>
      </div>

      <!-- Notes, Reasons, Trade Group -->
      <div class="form-row">
        <div>
          <label>Trade Group ID</label>
          <input id="edit-trade-group-id" name="trade_group_id" type="number" step="1" />
        </div>
      </div>
      <div>
        <label>Reason</label>
        <input id="edit-reason" name="reason" placeholder="Reason" />
      </div>
      <div>
        <label>Note</label>
        <input id="edit-note" name="note" placeholder="Note" />
      </div>

      <button type="submit" style="margin-top:15px;">Save Changes</button>
      <div id="edit-event-error" class="error"></div>
    </form>
  </div>
```

## 2. JavaScript Controller Integration

### Event Edit Click Handler

The click listener on `.event-edit` buttons is updated to load the event payload from the DOM row attributes and populate the form before opening the drawer:

```javascript
// Inside handleActionClick
if (btn.classList.contains("event-edit")) {
  const row = btn.closest("tr.journal-row") || document.querySelector(`tr.journal-row[data-event-id="${eventId}"]`);
  if (!row) return;

  let defaults;
  try {
    defaults = buildEditDefaultPayload(row);
  } catch (err) {
    window.alert(`Cannot open editor: ${err.message}`);
    return;
  }

  // Populate hidden inputs
  document.getElementById("edit-event-id").value = eventId;
  const eventType = row.dataset.eventType;
  document.getElementById("edit-event-type").value = eventType;
  document.getElementById("edit-drawer-title").textContent = `Edit Event #${eventId} (${eventType})`;

  // Populate common fields
  document.getElementById("edit-ts").value = (defaults.ts || "").slice(0, 19); // YYYY-MM-DDTHH:MM:SS
  document.getElementById("edit-ticker").value = defaults.ticker || "";
  document.getElementById("edit-market").value = defaults.market || "";
  document.getElementById("edit-currency").value = defaults.currency || "";
  document.getElementById("edit-fx-rate").value = defaults.fx_rate_to_base || "";
  document.getElementById("edit-trade-group-id").value = defaults.trade_group_id || "";
  document.getElementById("edit-reason").value = defaults.reason || "";
  document.getElementById("edit-note").value = defaults.note || "";

  // Reset conditional fields display
  document.getElementById("edit-buy-sell-fields").style.display = "none";
  document.getElementById("edit-qty-wrapper").style.display = "none";
  document.getElementById("edit-sl-fields").style.display = "none";
  document.getElementById("edit-cash-fields").style.display = "none";
  document.getElementById("edit-review-fields").style.display = "none";

  // Populate conditional fields
  if (eventType === "BUY" || eventType === "SELL") {
    document.getElementById("edit-buy-sell-fields").style.display = "flex";
    document.getElementById("edit-price").value = defaults.price || "";
    document.getElementById("edit-fee").value = defaults.fee || "0";
    if (eventType === "BUY") {
      document.getElementById("edit-qty-wrapper").style.display = "block";
      document.getElementById("edit-qty").value = defaults.qty || "";
      document.getElementById("edit-sl-fields").style.display = "flex";
      document.getElementById("edit-sl").value = defaults.sl || "";
      document.getElementById("edit-tp").value = defaults.tp || "";
    }
  } else if (eventType === "SL_UPDATE") {
    document.getElementById("edit-sl-fields").style.display = "flex";
    document.getElementById("edit-sl").value = defaults.sl || "";
    document.getElementById("edit-tp").value = defaults.tp || "";
  } else if (eventType === "CASHFLOW") {
    document.getElementById("edit-cash-fields").style.display = "flex";
    document.getElementById("edit-cash").value = defaults.cash_amount || "";
  } else if (eventType === "REVIEW") {
    document.getElementById("edit-review-fields").style.display = "flex";
    document.getElementById("edit-review").value = defaults.review_text || "";
  }

  // Clear previous errors and slide open drawer
  document.getElementById("edit-event-error").textContent = "";
  openDrawer("drawer-edit");
}
```

### Form Submit Handler

The submission of the form `#edit-event-form` sends the normalized payload using `PATCH`:

```javascript
document.getElementById("edit-event-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorDiv = document.getElementById("edit-event-error");
  errorDiv.textContent = "";

  const eventId = document.getElementById("edit-event-id").value;
  const eventType = document.getElementById("edit-edit-type")?.value || document.getElementById("edit-event-type").value;
  
  const payload = {
    ts: document.getElementById("edit-ts").value || null,
    ticker: document.getElementById("edit-ticker").value.trim() || null,
    market: document.getElementById("edit-market").value || null,
    currency: document.getElementById("edit-currency").value || null,
    fx_rate_to_base: toNullableNumber(document.getElementById("edit-fx-rate").value, "fx_rate_to_base"),
    trade_group_id: toNullableNumber(document.getElementById("edit-trade-group-id").value, "trade_group_id"),
    reason: document.getElementById("edit-reason").value.trim() || null,
    note: document.getElementById("edit-note").value.trim() || null,
  };

  if (eventType === "BUY" || eventType === "SELL") {
    payload.price = toNullableNumber(document.getElementById("edit-price").value, "price");
    payload.fee = toNullableNumber(document.getElementById("edit-fee").value, "fee");
    if (eventType === "BUY") {
      payload.qty = toNullableNumber(document.getElementById("edit-qty").value, "qty");
      payload.sl = toNullableNumber(document.getElementById("edit-sl").value, "sl");
      payload.tp = toNullableNumber(document.getElementById("edit-tp").value, "tp");
    }
  } else if (eventType === "SL_UPDATE") {
    payload.sl = toNullableNumber(document.getElementById("edit-sl").value, "sl");
    payload.tp = toNullableNumber(document.getElementById("edit-tp").value, "tp");
  } else if (eventType === "CASHFLOW") {
    payload.cash_amount = toNullableNumber(document.getElementById("edit-cash").value, "cash_amount");
  } else if (eventType === "REVIEW") {
    payload.review_text = document.getElementById("edit-review").value || null;
  }

  try {
    await jsonRequest(`/api/events/${eventId}`, "PATCH", payload);
    closeAllDrawers();
    await loadJournalPage(journalState.page, false);
  } catch (err) {
    errorDiv.textContent = `Save failed: ${err.message}`;
  }
});
```
