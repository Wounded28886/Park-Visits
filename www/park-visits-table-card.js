/**
 * Park Visits Table Card
 *
 * A spreadsheet-style table of every park tracked by the Park Visits
 * integration. Click a column header to sort by it; click the same header
 * again to reverse the direction. Also supports a quick text filter.
 *
 * Install: copy this file to config/www/park-visits-table-card.js, then add
 * it as a dashboard resource (Settings > Dashboards > Resources):
 *   URL: /local/park-visits-table-card.js
 *   Resource type: JavaScript module
 * Use in a dashboard with:
 *   type: custom:park-visits-table-card
 *   title: Top parks
 *   source: park_visits
 *   default_sort: rank        # rank | name | rating | categories | distance | our_rating
 *   default_direction: asc    # asc | desc
 *   show_filter: true
 */

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Each column knows how to pull a display string and a sortable value.
// Keeping those separate is what lets "4.9 (273)" sort by 4.9 rather than
// alphabetically, and lets blanks sort last regardless of direction.
const COLUMNS = [
  {
    key: "rank",
    label: "#",
    numeric: true,
    value: (s) => s.attributes.rank,
    display: (s) => (s.attributes.rank ?? "—"),
  },
  {
    key: "name",
    label: "Park",
    value: (s) => (s.attributes.friendly_name || s.entity_id).toLowerCase(),
    display: (s) => escapeHtml(s.attributes.friendly_name || s.entity_id),
  },
  {
    key: "rating",
    label: "Rating",
    numeric: true,
    value: (s) => s.attributes.rating,
    display: (s) =>
      s.attributes.rating != null
        ? `${Number(s.attributes.rating).toFixed(1)} <span class="muted">(${
            s.attributes.rating_count || 0
          })</span>`
        : "—",
  },
  {
    key: "categories",
    label: "Categories",
    value: (s) => (s.attributes.categories || []).join(", ").toLowerCase(),
    display: (s) =>
      (s.attributes.categories || [])
        .map((c) => `<span class="chip">${escapeHtml(c)}</span>`)
        .join("") || "—",
  },
  {
    key: "distance",
    label: "Distance",
    numeric: true,
    // Distance is the entity state for geo_location, not an attribute.
    value: (s) => parseFloat(s.state),
    display: (s) =>
      Number.isNaN(parseFloat(s.state)) ? "—" : `${parseFloat(s.state).toFixed(1)} km`,
  },
  {
    key: "our_rating",
    label: "Your rating",
    numeric: true,
    value: (s) => s.attributes.our_rating,
    display: (s) =>
      s.attributes.our_rating != null ? `${s.attributes.our_rating}/10` : "—",
  },
];

class ParkVisitsTableCard extends HTMLElement {
  constructor() {
    super();
    this._sortKey = "rank";
    this._sortDir = "asc";
    this._filter = "";
    this._signature = null;
  }

  setConfig(config) {
    this.config = {
      title: "Parks",
      source: "park_visits",
      default_sort: "rank",
      default_direction: "asc",
      show_filter: true,
      ...config,
    };
    if (COLUMNS.some((c) => c.key === this.config.default_sort)) {
      this._sortKey = this.config.default_sort;
    }
    this._sortDir = this.config.default_direction === "desc" ? "desc" : "asc";
    this._built = false;
    this._signature = null;
    if (this.isConnected) this._build();
  }

  connectedCallback() {
    // Same custom-element upgrade race as the map card: a .hass assigned
    // before this class was attached would shadow the setter permanently.
    this._upgradeProperty("hass");
    this._build();
  }

  _upgradeProperty(prop) {
    if (Object.prototype.hasOwnProperty.call(this, prop)) {
      const value = this[prop];
      delete this[prop];
      this[prop] = value;
    }
  }

  set hass(hass) {
    this._hass = hass;
    this._renderRows();
  }

  _build() {
    if (this._built || !this.config) return;
    this._built = true;

    this.innerHTML = `
      <ha-card header="${escapeHtml(this.config.title)}">
        <div class="card-content">
          ${
            this.config.show_filter
              ? `<input class="pv-filter" type="search" placeholder="Filter parks…" />`
              : ""
          }
          <div class="pv-scroll">
            <table class="pv-table">
              <thead><tr>${COLUMNS.map(
                (c) =>
                  `<th data-key="${c.key}" title="Sort by ${escapeHtml(
                    c.label
                  )}"><span class="pv-th">${escapeHtml(
                    c.label
                  )}<span class="pv-arrow"></span></span></th>`
              ).join("")}</tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div class="pv-count"></div>
        </div>
      </ha-card>
      <style>
        .pv-scroll { overflow-x: auto; }
        .pv-table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .pv-table th, .pv-table td {
          text-align: left; padding: 8px 10px;
          border-bottom: 1px solid var(--divider-color, #333);
          vertical-align: top;
        }
        .pv-table th {
          cursor: pointer; user-select: none; white-space: nowrap;
          position: sticky; top: 0; z-index: 1;
          background: var(--card-background-color, #1c1c1c);
        }
        .pv-table th:hover { color: var(--primary-color, #03a9f4); }
        .pv-th { display: inline-flex; align-items: center; gap: 4px; }
        .pv-arrow { font-size: 10px; opacity: 0.9; width: 8px; display: inline-block; }
        .pv-table tbody tr:hover { background: var(--secondary-background-color, #222); }
        .pv-table td.num { text-align: right; white-space: nowrap; }
        .muted { opacity: 0.6; }
        .chip {
          display: inline-block; background: var(--secondary-background-color, #2a2a2a);
          border-radius: 12px; padding: 1px 8px; margin: 1px 4px 1px 0;
          font-size: 12px; white-space: nowrap;
        }
        .pv-filter {
          width: 100%; box-sizing: border-box; margin-bottom: 8px; padding: 6px 8px;
          border-radius: 6px; border: 1px solid var(--divider-color, #333);
          background: var(--primary-background-color, #111);
          color: var(--primary-text-color, #eee); font: inherit;
        }
        .pv-count { margin-top: 8px; font-size: 12px; opacity: 0.7; }
      </style>
    `;

    this.querySelectorAll("th").forEach((th) => {
      th.addEventListener("click", () => this._onHeaderClick(th.dataset.key));
    });
    const filterEl = this.querySelector(".pv-filter");
    if (filterEl) {
      filterEl.addEventListener("input", (e) => {
        this._filter = e.target.value.trim().toLowerCase();
        this._signature = null; // force redraw
        this._renderRows();
      });
    }
    this._renderRows();
  }

  _onHeaderClick(key) {
    if (!key) return;
    if (this._sortKey === key) {
      this._sortDir = this._sortDir === "asc" ? "desc" : "asc";
    } else {
      this._sortKey = key;
      // Text reads best A→Z; numbers people usually want best/nearest first,
      // and rank 1 is "best", so ascending is the sensible default for both.
      this._sortDir = "asc";
    }
    this._signature = null; // sort changed — force a redraw
    this._renderRows();
  }

  _rows() {
    if (!this._hass) return [];
    let rows = Object.values(this._hass.states).filter(
      (s) => s.attributes.source === this.config.source
    );
    if (this._filter) {
      rows = rows.filter((s) => {
        const hay = `${s.attributes.friendly_name || ""} ${(
          s.attributes.categories || []
        ).join(" ")} ${s.attributes.address || ""}`.toLowerCase();
        return hay.includes(this._filter);
      });
    }
    const col = COLUMNS.find((c) => c.key === this._sortKey) || COLUMNS[0];
    const dir = this._sortDir === "desc" ? -1 : 1;
    return rows.sort((a, b) => {
      const va = col.value(a);
      const vb = col.value(b);
      // Missing values always sink to the bottom, in both directions —
      // otherwise reversing the sort fills the top with blank rows.
      const aMissing = va == null || (typeof va === "number" && Number.isNaN(va));
      const bMissing = vb == null || (typeof vb === "number" && Number.isNaN(vb));
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }

  _renderRows() {
    if (!this._built || !this._hass) return;
    const rows = this._rows();

    // Redrawing 100 rows of innerHTML on every state push is wasteful, so
    // skip when nothing that affects this table has actually changed.
    const signature = `${this._sortKey}|${this._sortDir}|${this._filter}|${rows.length}|${rows
      .map((s) => `${s.entity_id}:${s.last_updated}`)
      .join(",")}`;
    if (signature === this._signature) return;
    this._signature = signature;

    const tbody = this.querySelector("tbody");
    tbody.innerHTML = rows
      .map(
        (s) =>
          `<tr>${COLUMNS.map(
            (c) => `<td class="${c.numeric ? "num" : ""}">${c.display(s)}</td>`
          ).join("")}</tr>`
      )
      .join("");

    this.querySelectorAll("th").forEach((th) => {
      const arrow = th.querySelector(".pv-arrow");
      if (!arrow) return;
      arrow.textContent =
        th.dataset.key === this._sortKey ? (this._sortDir === "asc" ? "▲" : "▼") : "";
    });

    const countEl = this.querySelector(".pv-count");
    if (countEl) {
      const col = COLUMNS.find((c) => c.key === this._sortKey);
      countEl.textContent = `${rows.length} park${rows.length === 1 ? "" : "s"} — sorted by ${
        col ? col.label : this._sortKey
      } (${this._sortDir === "asc" ? "ascending" : "descending"})`;
    }
  }

  getCardSize() {
    return 12;
  }
}

customElements.define("park-visits-table-card", ParkVisitsTableCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "park-visits-table-card",
  name: "Park Visits Table",
  description: "Sortable, filterable table of tracked parks.",
});
