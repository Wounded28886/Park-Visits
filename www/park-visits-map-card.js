/**
 * Park Visits Map Card
 *
 * Plots every geo_location entity produced by the Park Visits integration
 * on a Leaflet map. Clicking a marker opens a popup with the park's Google
 * rating, categories and address, your own past rating/note if any, and a
 * small form to submit a new one — which calls the park_visits.rate_park
 * service.
 *
 * Install: copy this file to config/www/park-visits-map-card.js, then add
 * it as a dashboard resource (Settings > Dashboards > Resources):
 *   URL: /local/park-visits-map-card.js
 *   Resource type: JavaScript module
 * Use in a dashboard with:
 *   type: custom:park-visits-map-card
 *   title: Parks
 *   source: park_visits
 */
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";

let leafletLoadPromise = null;

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (leafletLoadPromise) return leafletLoadPromise;

  leafletLoadPromise = new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.src = LEAFLET_JS;
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error("park-visits-map-card: failed to load Leaflet"));
    document.head.appendChild(script);
  });
  return leafletLoadPromise;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

class ParkVisitsMapCard extends HTMLElement {
  setConfig(config) {
    this.config = {
      title: "Parks",
      source: "park_visits",
      height: "500px",
      default_zoom: 8,
      ...config,
    };
    // entity_id -> { marker: L.Marker, signature: string }
    this._markers = new Map();
    this._fitDone = false;
  }

  connectedCallback() {
    this._buildCard();
  }

  disconnectedCallback() {
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._markers.clear();
    this._built = false;
    this._fitDone = false;
  }

  async _buildCard() {
    if (this._built) return;
    this._built = true;

    this.innerHTML = `
      <ha-card header="${escapeHtml(this.config.title)}">
        <div class="card-content">
          <div id="map" style="height: ${escapeHtml(this.config.height)}; border-radius: var(--ha-card-border-radius, 12px); overflow: hidden;"></div>
        </div>
      </ha-card>
      <style>
        .park-visits-popup { min-width: 240px; }
        .park-visits-popup h3 { margin: 0 0 4px 0; font-size: 16px; }
        .park-visits-popup .categories { margin: 4px 0; }
        .park-visits-popup .chip {
          display: inline-block; background: var(--secondary-background-color, #eee);
          border-radius: 12px; padding: 2px 8px; margin: 2px 4px 2px 0; font-size: 12px;
        }
        .park-visits-popup .rating { font-weight: 600; }
        .park-visits-popup .address { font-size: 12px; opacity: 0.8; margin: 4px 0; }
        .park-visits-popup .our-review {
          margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--divider-color, #ccc);
        }
        .park-visits-popup form { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
        .park-visits-popup label { font-size: 12px; opacity: 0.8; }
        .park-visits-popup input[type=number], .park-visits-popup textarea {
          width: 100%; box-sizing: border-box; padding: 4px; font: inherit;
        }
        .park-visits-popup button {
          align-self: flex-start; padding: 6px 14px; border: none; border-radius: 4px;
          background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff);
          cursor: pointer; font: inherit;
        }
        .park-visits-popup .maps-link { font-size: 12px; }
        .park-visits-popup .saved-flag { font-size: 12px; color: var(--success-color, #4caf50); }
      </style>
    `;

    const L = await loadLeaflet();
    const mapEl = this.querySelector("#map");
    this._map = L.map(mapEl);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(this._map);
    this._map.setView(
      [this.config.latitude ?? 0, this.config.longitude ?? 0],
      this.config.default_zoom
    );

    if (this._pendingHass) {
      this._render(this._pendingHass);
    }
  }

  set hass(hass) {
    this._pendingHass = hass;
    if (this._map) {
      this._render(hass);
    }
  }

  _parkEntities(hass) {
    return Object.values(hass.states).filter((s) => s.attributes.source === this.config.source);
  }

  _render(hass) {
    const L = window.L;
    const entities = this._parkEntities(hass);
    const seen = new Set();
    const bounds = [];

    for (const state of entities) {
      const lat = state.attributes.latitude;
      const lon = state.attributes.longitude;
      if (lat == null || lon == null) continue;

      seen.add(state.entity_id);
      bounds.push([lat, lon]);

      const signature = `${state.last_updated}|${state.attributes.our_rating}`;
      const existing = this._markers.get(state.entity_id);
      if (existing && existing.signature === signature) {
        continue; // unchanged since last render — skip rebuilding the marker/popup
      }

      const rated = state.attributes.our_rating != null;
      const icon = L.divIcon({
        className: "",
        html: `<div style="
          width: 14px; height: 14px; border-radius: 50%;
          background: ${rated ? "#f9a825" : "#03a9f4"};
          border: 2px solid white; box-shadow: 0 0 2px rgba(0,0,0,0.5);
        "></div>`,
        iconSize: [14, 14],
      });

      let marker = existing?.marker;
      if (!marker) {
        marker = L.marker([lat, lon], { icon });
        marker.addTo(this._map);
        marker.on("popupopen", (e) => this._wirePopup(e.popup));
      } else {
        marker.setIcon(icon);
        marker.setLatLng([lat, lon]);
      }

      marker.bindPopup(() => this._popupContent(hass.states[state.entity_id]), { maxWidth: 300 });
      if (marker.isPopupOpen()) {
        marker.setPopupContent(this._popupContent(state));
        this._wirePopup(marker.getPopup());
      }

      this._markers.set(state.entity_id, { marker, signature });
    }

    for (const [entityId, { marker }] of this._markers) {
      if (!seen.has(entityId)) {
        marker.remove();
        this._markers.delete(entityId);
      }
    }

    if (!this._fitDone && bounds.length) {
      this._map.fitBounds(bounds, { padding: [20, 20] });
      this._fitDone = true;
    }
  }

  _popupContent(state) {
    const a = state.attributes;
    const categories = (a.categories || [])
      .map((c) => `<span class="chip">${escapeHtml(c)}</span>`)
      .join("");
    const rating =
      a.rating != null ? `★ ${Number(a.rating).toFixed(1)} (${a.rating_count || 0})` : "No Google rating yet";
    const hasReview = a.our_reviewed_at != null;
    const reviewedLine = hasReview
      ? `<div class="our-review"><strong>Your rating:</strong> ${escapeHtml(a.our_rating)}/10${
          a.our_note ? `<br>${escapeHtml(a.our_note)}` : ""
        }</div>`
      : "";

    const div = document.createElement("div");
    div.className = "park-visits-popup";
    div.innerHTML = `
      <h3>${escapeHtml(a.friendly_name || state.entity_id)}</h3>
      <div class="rating">${rating}</div>
      <div class="categories">${categories}</div>
      <div class="address">${escapeHtml(a.address || "")}</div>
      ${
        a.google_maps_uri
          ? `<a class="maps-link" href="${escapeHtml(a.google_maps_uri)}" target="_blank" rel="noopener">Open in Google Maps</a>`
          : ""
      }
      ${reviewedLine}
      <form data-place-id="${escapeHtml(a.place_id || "")}">
        <label>${hasReview ? "Update your rating" : "Rate this park"} (0-10)</label>
        <input type="number" name="rating" min="0" max="10" step="0.5" value="${escapeHtml(a.our_rating ?? "")}" required>
        <label>Note</label>
        <textarea name="note" rows="2">${escapeHtml(a.our_note || "")}</textarea>
        <button type="submit">Save</button>
        <span class="saved-flag" hidden>Saved ✓</span>
      </form>
    `;
    return div;
  }

  _wirePopup(popup) {
    const container = popup.getElement();
    const form = container && container.querySelector("form");
    if (!form || form._wired) return;
    form._wired = true;
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const placeId = form.dataset.placeId;
      const rating = parseFloat(form.rating.value);
      const note = form.note.value;
      if (!placeId || Number.isNaN(rating) || !this._pendingHass) return;
      this._pendingHass.callService("park_visits", "rate_park", {
        place_id: placeId,
        rating,
        note,
      });
      const flag = form.querySelector(".saved-flag");
      if (flag) flag.hidden = false;
    });
  }

  getCardSize() {
    return 6;
  }
}

customElements.define("park-visits-map-card", ParkVisitsMapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "park-visits-map-card",
  name: "Park Visits Map",
  description: "Map of tracked parks with click-to-rate popups.",
});
