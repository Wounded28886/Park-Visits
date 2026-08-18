/**
 * Park Visits Gallery Card
 *
 * A collage of every photo we've uploaded with a park review. Clicking a
 * photo opens it large, with the park's name and our review beside it.
 *
 * Install: copy this file to config/www/park-visits-gallery-card.js, then
 * add it as a dashboard resource (Settings > Dashboards > Resources):
 *   URL: /local/park-visits-gallery-card.js
 *   Resource type: JavaScript module
 * Use in a dashboard with:
 *   type: custom:park-visits-gallery-card
 *   title: Our photos
 *   columns: 4          # optional; omit to fit as many as the width allows
 */

function escapeHtml(value) {
  // `!= null` (not `??`) deliberately — nullish coalescing is ES2020 and
  // throws a hard SyntaxError on old embedded browsers (e.g. Samsung Family
  // Hub fridge displays), which kills the whole script before
  // customElements.define() ever runs.
  return String(value != null ? value : "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// "YYYY-MM-DD" -> locale date string, without the UTC-shift-by-a-day trap
// that `new Date("YYYY-MM-DD")` alone falls into near midnight.
function formatLocalDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(`${dateStr}T00:00:00`);
  return Number.isNaN(d.getTime()) ? dateStr : d.toLocaleDateString();
}

class ParkVisitsGalleryCard extends HTMLElement {
  constructor() {
    super();
    this._items = [];
    this._tiles = [];
    // The subset currently on screen. The lightbox pages through this, not
    // _tiles, so "next" follows what you can actually see.
    this._visible = [];
    this._openIndex = null;
    this._loaded = false;
    this._error = null;
    this._parkFilter = "";
    this._tagFilter = "";
  }

  setConfig(config) {
    this.config = {
      title: "Our park photos",
      columns: null,
      show_filter: true,
      ...config,
    };
    this._built = false;
    if (this.isConnected) this._build();
  }

  connectedCallback() {
    // Same custom-element upgrade race as the table card: a .hass assigned
    // before this class was registered would shadow the setter permanently.
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
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._load();
      return;
    }
    // The gallery is served by an HTTP endpoint rather than entity state, so
    // it can't just re-read hass. Reload when the number of stored photos
    // changes — that covers uploads and deletions without polling, and
    // without redrawing on every unrelated state push (which would fight the
    // open lightbox the same way it did in the table card).
    const total = this._photoCountFromStates(hass);
    if (this._lastPhotoTotal != null && total !== this._lastPhotoTotal) {
      this._load();
    }
    this._lastPhotoTotal = total;
  }

  _photoCountFromStates(hass) {
    return Object.values(hass.states).reduce(
      (sum, s) =>
        s.attributes && s.attributes.source === "park_visits"
          ? sum + (s.attributes.our_photo_count || 0)
          : sum,
      0
    );
  }

  _build() {
    if (this._built || !this.config) return;
    this._built = true;
    this.innerHTML = `
      <ha-card header="${escapeHtml(this.config.title)}">
        <div class="card-content">
          ${this.config.show_filter ? `<div class="pvg-filters"></div>` : ""}
          <div class="pvg-status">Loading…</div>
          <div class="pvg-grid"></div>
        </div>
      </ha-card>
      <div class="pvg-dialog-root"></div>
      ${STYLES}
    `;
    if (this.config.columns) {
      this.querySelector(".pvg-grid").style.gridTemplateColumns =
        `repeat(${parseInt(this.config.columns, 10)}, 1fr)`;
    }
    if (this._hass) this._load();
  }

  async _load() {
    if (!this._hass || !this._built) return;
    try {
      const data = await this._hass.callApi("GET", "park_visits/gallery");
      this._items = data.parks || [];
      this._error = null;
    } catch (err) {
      this._error = "Couldn't load the gallery.";
      this._items = [];
    }
    this._lastPhotoTotal = this._photoCountFromStates(this._hass);
    await this._buildTiles();
    this._renderFilters();
    this._renderGrid();
  }

  /**
   * Park and tag pickers, rebuilt from whatever the gallery currently holds.
   *
   * The tag picker only appears once something is actually tagged — with no
   * Immich server there's nothing to pick from, and an empty dropdown would
   * just be clutter.
   */
  _renderFilters() {
    const host = this.querySelector(".pvg-filters");
    if (!host) return;

    const parks = this._items
      .map((p) => ({ id: p.place_id, name: p.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
    const tags = [...new Set(this._items.map((p) => p.immich_tag).filter(Boolean))].sort(
      (a, b) => a.localeCompare(b)
    );

    // A filter whose target has since disappeared would hide everything with
    // no way back, so drop selections that no longer exist.
    if (this._parkFilter && !parks.some((p) => p.id === this._parkFilter)) {
      this._parkFilter = "";
    }
    if (this._tagFilter && !tags.includes(this._tagFilter)) this._tagFilter = "";

    const option = (value, label, selected) =>
      `<option value="${escapeHtml(value)}"${selected ? " selected" : ""}>${escapeHtml(
        label
      )}</option>`;

    host.innerHTML = `
      <label class="pvg-filter-field">
        <span>Park</span>
        <select class="pvg-park-filter">
          ${option("", "All parks", !this._parkFilter)}
          ${parks.map((p) => option(p.id, p.name, p.id === this._parkFilter)).join("")}
        </select>
      </label>
      ${
        tags.length
          ? `<label class="pvg-filter-field">
               <span>Immich tag</span>
               <select class="pvg-tag-filter">
                 ${option("", "All tags", !this._tagFilter)}
                 ${tags.map((t) => option(t, t, t === this._tagFilter)).join("")}
               </select>
             </label>`
          : ""
      }
      ${
        this._parkFilter || this._tagFilter
          ? `<button class="pvg-filter-clear">Clear</button>`
          : ""
      }`;

    const onChange = (key) => (ev) => {
      this[key] = ev.target.value;
      // Indices are into the visible set, so a stale lightbox would be
      // pointing at the wrong photo.
      this._closeLightbox();
      this._renderFilters();
      this._renderGrid();
    };
    const parkSelect = host.querySelector(".pvg-park-filter");
    if (parkSelect) parkSelect.addEventListener("change", onChange("_parkFilter"));
    const tagSelect = host.querySelector(".pvg-tag-filter");
    if (tagSelect) tagSelect.addEventListener("change", onChange("_tagFilter"));
    const clear = host.querySelector(".pvg-filter-clear");
    if (clear) {
      clear.addEventListener("click", () => {
        this._parkFilter = "";
        this._tagFilter = "";
        this._closeLightbox();
        this._renderFilters();
        this._renderGrid();
      });
    }
  }

  /**
   * Tiles matching the current filters.
   *
   * Filtering by tag keeps only photos that actually carry it — the Immich
   * ones. A park's uploaded photos aren't tagged in Immich at all, so
   * including them under a tag filter would be a lie.
   */
  _filteredTiles() {
    return this._tiles.filter((tile) => {
      if (this._parkFilter && tile.park.place_id !== this._parkFilter) return false;
      if (this._tagFilter && !(tile.fullPath && tile.park.immich_tag === this._tagFilter)) {
        return false;
      }
      return true;
    });
  }

  async _buildTiles() {
    // One flat list of photos across all parks, each remembering which park
    // it came from so the lightbox can show that review.
    // Every path is signed in one burst rather than one after another: a
    // gallery spanning a few tagged parks can run to hundreds of photos, and
    // each signature is its own WebSocket round-trip.
    const pending = [];
    for (const park of this._items) {
      for (const filename of park.photos) {
        pending.push({
          park,
          filename,
          path: `/api/park_visits/photo/${park.place_id}/${filename}`,
        });
      }
      // Photos matched by the park's Immich tag sit alongside the uploaded
      // ones; they're relayed by the integration, so they sign the same way.
      // Tiles use Immich's small size; the lightbox fetches the full preview
      // for the single photo being opened.
      for (const assetId of park.immich_assets || []) {
        pending.push({
          park,
          filename: null,
          path: `/api/park_visits/immich/thumb/thumbnail/${assetId}`,
          fullPath: `/api/park_visits/immich/thumb/preview/${assetId}`,
        });
      }
    }

    const urls = await Promise.all(pending.map((p) => this._signedPath(p.path)));
    this._tiles = pending
      .map((p, i) => ({
        park: p.park,
        filename: p.filename,
        url: urls[i],
        fullPath: p.fullPath,
      }))
      .filter((t) => t.url);
    this._loaded = true;
  }

  async _signedPath(path) {
    // <img> can't send an auth header, so have HA sign the media path.
    try {
      const res = await this._hass.callWS({
        type: "auth/sign_path",
        path,
        expires: 3600,
      });
      return res.path;
    } catch (err) {
      return null;
    }
  }

  _renderGrid() {
    const status = this.querySelector(".pvg-status");
    const grid = this.querySelector(".pvg-grid");
    if (!status || !grid) return;

    if (this._error) {
      status.textContent = this._error;
      grid.innerHTML = "";
      return;
    }
    if (!this._tiles.length) {
      status.textContent =
        "No photos yet — upload one with a review, or tag a park's photos in Immich.";
      grid.innerHTML = "";
      return;
    }

    this._visible = this._filteredTiles();
    if (!this._visible.length) {
      status.textContent = "No photos match that filter.";
      grid.innerHTML = "";
      return;
    }

    const parkCount = new Set(this._visible.map((t) => t.park.place_id)).size;
    const filtered = this._visible.length !== this._tiles.length;
    status.textContent =
      `${this._visible.length} photo${this._visible.length === 1 ? "" : "s"}` +
      ` across ${parkCount} park${parkCount === 1 ? "" : "s"}` +
      (filtered ? ` (of ${this._tiles.length})` : "");

    grid.innerHTML = this._visible
      .map(
        (tile, index) => `
        <button class="pvg-tile" data-index="${index}" title="${escapeHtml(
          tile.park.name
        )}">
          <img src="${escapeHtml(tile.url)}" loading="lazy" alt="${escapeHtml(
          tile.park.name
        )}">
          <span class="pvg-caption">${escapeHtml(tile.park.name)}</span>
        </button>`
      )
      .join("");

    grid.querySelectorAll(".pvg-tile").forEach((button) => {
      button.addEventListener("click", () =>
        this._openLightbox(parseInt(button.dataset.index, 10))
      );
      const img = button.querySelector("img");
      // A signed URL can expire or the file can vanish; drop dead tiles
      // rather than leaving grey boxes.
      img.addEventListener("error", () => button.remove());
    });
  }

  _openLightbox(index) {
    this._openIndex = index;
    this._renderLightbox();
    // Tiles are the small Immich size; swap in the full preview once its
    // signed URL arrives, so opening a photo doesn't wait on it.
    const tile = this._visible[index];
    if (tile && tile.fullPath && !tile.fullUrl) {
      this._signedPath(tile.fullPath).then((url) => {
        if (!url || this._openIndex !== index) return;
        tile.fullUrl = url;
        this._renderLightbox();
      });
    }
  }

  _closeLightbox() {
    this._openIndex = null;
    this.querySelector(".pvg-dialog-root").innerHTML = "";
  }

  _renderLightbox() {
    const root = this.querySelector(".pvg-dialog-root");
    if (!root) return;
    if (this._openIndex == null || !this._visible[this._openIndex]) {
      root.innerHTML = "";
      return;
    }
    const tile = this._visible[this._openIndex];
    const { park } = tile;
    const url = tile.fullUrl || tile.url;
    const many = this._visible.length > 1;

    const ratingLine = (label, value) =>
      value != null ? `<div><strong>${label}:</strong> ${escapeHtml(value)}/10</div>` : "";
    const review = park.visit_date
      ? `
        <div class="pvg-review">
          ${ratingLine("Overall Rating", park.overall_rating)}
          ${ratingLine("Kids Rating", park.kids_rating)}
          ${ratingLine("Mums Rating", park.mums_rating)}
          ${ratingLine("Dads Rating", park.dads_rating)}
          ${park.liked ? `<div><strong>Liked:</strong> ${escapeHtml(park.liked)}</div>` : ""}
          ${
            park.disliked
              ? `<div><strong>Didn't like:</strong> ${escapeHtml(park.disliked)}</div>`
              : ""
          }
          ${park.note ? `<div><strong>Notes:</strong> ${escapeHtml(park.note)}</div>` : ""}
          <div class="pvg-muted">Visited ${escapeHtml(formatLocalDate(park.visit_date))}</div>
        </div>`
      : `<div class="pvg-muted">Photo added, but this park hasn't been reviewed yet.</div>`;

    root.innerHTML = `
      <div class="pvg-backdrop">
        <div class="pvg-dialog" role="dialog" aria-modal="true">
          <div class="pvg-dialog-head">
            <h2>${escapeHtml(park.name)}${
      park.still_tracked ? "" : ` <span class="pvg-muted">(no longer tracked)</span>`
    }</h2>
            <button class="pvg-close" title="Close">✕</button>
          </div>
          <img class="pvg-full" src="${escapeHtml(url)}" alt="">
          <div class="pvg-dialog-body">
            ${review}
            ${
              many
                ? `<div class="pvg-nav">
                     <button class="pvg-prev">‹ Previous</button>
                     <span class="pvg-muted">${this._openIndex + 1} of ${
                    this._visible.length
                  }</span>
                     <button class="pvg-next">Next ›</button>
                   </div>`
                : ""
            }
          </div>
        </div>
      </div>`;

    root.querySelector(".pvg-close").addEventListener("click", () => this._closeLightbox());
    root.querySelector(".pvg-backdrop").addEventListener("click", (ev) => {
      if (ev.target.classList.contains("pvg-backdrop")) this._closeLightbox();
    });
    const prev = root.querySelector(".pvg-prev");
    const next = root.querySelector(".pvg-next");
    if (prev)
      prev.addEventListener("click", () =>
        this._openLightbox((this._openIndex - 1 + this._visible.length) % this._visible.length)
      );
    if (next)
      next.addEventListener("click", () =>
        this._openLightbox((this._openIndex + 1) % this._visible.length)
      );
  }

  getCardSize() {
    return 8;
  }
}

const STYLES = `
<style>
  .pvg-filters {
    display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; margin-bottom: 10px;
  }
  .pvg-filter-field { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .pvg-filter-field span { font-size: 12px; opacity: 0.7; }
  .pvg-filters select {
    padding: 6px; font: inherit; border-radius: 6px; max-width: 260px;
    border: 1px solid var(--divider-color, #333);
    background: var(--primary-background-color, #111); color: var(--primary-text-color, #eee);
  }
  .pvg-filter-clear {
    padding: 7px 12px; font: inherit; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--divider-color, #333);
    background: var(--secondary-background-color, #2a2a2a);
    color: var(--primary-text-color, #eee);
  }
  .pvg-filter-clear:hover { border-color: var(--primary-color, #03a9f4); }
  .pvg-status { font-size: 13px; opacity: 0.7; margin-bottom: 10px; }
  .pvg-grid {
    display: grid; gap: 8px;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  }
  .pvg-tile {
    position: relative; padding: 0; border: none; cursor: pointer;
    border-radius: 10px; overflow: hidden; background: var(--secondary-background-color, #222);
    aspect-ratio: 1 / 1;
  }
  .pvg-tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .pvg-tile:hover img { transform: scale(1.04); transition: transform 0.15s ease; }
  .pvg-caption {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 6px 8px;
    font-size: 12px; text-align: left; color: #fff;
    background: linear-gradient(transparent, rgba(0,0,0,0.75));
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .pvg-muted { opacity: 0.65; }
  .pvg-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.75);
    display: flex; align-items: flex-start; justify-content: center;
    z-index: 9999; padding: 24px 12px; overflow-y: auto;
  }
  .pvg-dialog {
    background: var(--card-background-color, #1c1c1c);
    color: var(--primary-text-color, #eee);
    border-radius: var(--ha-card-border-radius, 12px);
    max-width: 720px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    overflow: hidden;
  }
  .pvg-dialog-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; border-bottom: 1px solid var(--divider-color, #333);
  }
  .pvg-dialog-head h2 { margin: 0; font-size: 18px; }
  .pvg-close {
    background: none; border: none; color: inherit; font-size: 18px;
    cursor: pointer; opacity: 0.7;
  }
  .pvg-close:hover { opacity: 1; }
  .pvg-full { width: 100%; max-height: 60vh; object-fit: contain; background: #000; display: block; }
  .pvg-dialog-body { padding: 16px; }
  .pvg-review { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .pvg-nav {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 16px; gap: 12px;
  }
  .pvg-nav button {
    padding: 6px 14px; border: 1px solid var(--divider-color, #333); border-radius: 6px;
    background: var(--secondary-background-color, #2a2a2a);
    color: var(--primary-text-color, #eee); cursor: pointer; font: inherit;
  }
  .pvg-nav button:hover { border-color: var(--primary-color, #03a9f4); }
</style>`;

customElements.define("park-visits-gallery-card", ParkVisitsGalleryCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "park-visits-gallery-card",
  name: "Park Visits Gallery",
  description: "Collage of photos from our park reviews.",
});
