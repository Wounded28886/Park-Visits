/**
 * Park Visits Table Card
 *
 * A spreadsheet-style table of every park tracked by the Park Visits
 * integration. Click a column header to sort by it; click again to reverse.
 * Click a park's name to open its detail panel: Google's rating, photos and
 * reviews, plus our own review and a form to write or update it (rating,
 * what we liked, what we didn't, notes and photos).
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
    display: (s) => s.attributes.rank ?? "—",
  },
  {
    key: "name",
    label: "Park",
    value: (s) => (s.attributes.friendly_name || s.entity_id).toLowerCase(),
    display: (s) =>
      `<a href="#" class="pv-name" data-entity="${escapeHtml(
        s.entity_id
      )}">${escapeHtml(s.attributes.friendly_name || s.entity_id)}</a>`,
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
    display: (s) => {
      const bits = [];
      if (s.attributes.our_rating != null) bits.push(`${s.attributes.our_rating}/10`);
      if (s.attributes.our_photo_count)
        bits.push(`<span class="muted">📷${s.attributes.our_photo_count}</span>`);
      return bits.join(" ") || "—";
    },
  },
  {
    key: "review",
    label: "",
    sortable: false,
    display: (s) =>
      `<button class="pv-rowbtn" data-entity="${escapeHtml(s.entity_id)}">${
        s.attributes.our_reviewed_at != null ? "Edit" : "Review"
      }</button>`,
  },
];

class ParkVisitsTableCard extends HTMLElement {
  constructor() {
    super();
    this._sortKey = "rank";
    this._sortDir = "asc";
    this._filter = "";
    this._signature = null;
    this._openEntity = null;
    this._details = null;
    this._detailsError = null;
    this._formOpen = false;
    this._busy = false;
    this._photoItems = [];
    this._lightboxIndex = null;
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
    // If HA assigned .hass before this class was registered, the value sits
    // as an own property and would shadow the setter forever.
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
    this._renderStatusStrip();
    if (this._openEntity) this._maybeRerenderDialog();
  }

  /* -------------------------------------------------- last visited / next */

  /**
   * Find one of our summary sensors by its role attribute.
   *
   * Entity ids get suffixed when there are name clashes and users rename
   * them, so matching on a marker attribute is more durable than hardcoding
   * sensor.next_park.
   */
  _sensorByRole(role) {
    if (!this._hass) return null;
    return (
      Object.values(this._hass.states).find(
        (s) => s.attributes && s.attributes.park_visits_role === role
      ) || null
    );
  }

  _renderStatusStrip() {
    const strip = this.querySelector(".pv-status-strip");
    if (!strip || !this._hass) return;

    const next = this._sensorByRole("next_park");
    const last = this._sensorByRole("last_visited");
    // Nothing to show if the integration predates these sensors.
    if (!next && !last) {
      strip.innerHTML = "";
      return;
    }

    const signature = JSON.stringify([
      next && [next.state, next.attributes.place_id, next.attributes.distance_km],
      last && [last.state, last.attributes.place_id, last.attributes.reviewed_at],
      this._pickerOpen,
    ]);
    if (signature === this._stripSignature) return;
    this._stripSignature = signature;

    const hasNext = next && next.attributes.place_id;
    const hasLast = last && last.attributes.place_id;

    const lastBody = hasLast
      ? `<div class="pv-strip-name">${escapeHtml(last.state)}</div>
         <div class="pv-strip-sub">${
           last.attributes.our_rating != null
             ? `We rated it ${escapeHtml(last.attributes.our_rating)}/10`
             : "Not rated"
         }${
          last.attributes.reviewed_at
            ? ` · ${escapeHtml(new Date(last.attributes.reviewed_at).toLocaleDateString())}`
            : ""
        }</div>`
      : `<div class="pv-strip-empty">No visits recorded yet — review a park to log one.</div>`;

    const nextBody = hasNext
      ? `<div class="pv-strip-name">${escapeHtml(next.state)}</div>
         <div class="pv-strip-sub">${
           next.attributes.rating != null
             ? `★ ${Number(next.attributes.rating).toFixed(1)}`
             : "No Google rating"
         }${
          next.attributes.distance_km != null
            ? ` · ${Number(next.attributes.distance_km).toFixed(1)} km away`
            : ""
        }</div>`
      : `<div class="pv-strip-empty">Nothing planned yet.</div>`;

    strip.innerHTML = `
      <div class="pv-strip">
        <div class="pv-strip-box">
          <div class="pv-strip-label">🕘 Last visited</div>
          ${lastBody}
          ${
            hasLast
              ? `<div class="pv-strip-actions">
                   <button class="pv-strip-btn pv-open-last" data-place="${escapeHtml(
                     last.attributes.place_id
                   )}">View</button>
                 </div>`
              : ""
          }
        </div>
        <div class="pv-strip-box pv-strip-next">
          <div class="pv-strip-label">📍 Next up</div>
          ${nextBody}
          <div class="pv-strip-actions">
            <button class="pv-strip-btn pv-pick-next">${
              hasNext ? "Change" : "Choose a park"
            }</button>
            ${
              hasNext
                ? `<button class="pv-strip-btn pv-open-next" data-place="${escapeHtml(
                    next.attributes.place_id
                  )}">View</button>
                   <button class="pv-strip-btn pv-clear-next">Clear</button>`
                : ""
            }
          </div>
          ${this._pickerOpen ? this._pickerHtml() : ""}
        </div>
      </div>`;

    this._wireStatusStrip(strip);
  }

  _pickerHtml() {
    const parks = Object.values(this._hass.states)
      .filter((s) => s.attributes.source === this.config.source)
      .sort((a, b) => (a.attributes.rank || 0) - (b.attributes.rank || 0));
    return `
      <div class="pv-picker">
        <select class="pv-picker-select">
          <option value="">— pick a park —</option>
          ${parks
            .map(
              (s) =>
                `<option value="${escapeHtml(s.attributes.place_id)}">#${
                  s.attributes.rank
                } ${escapeHtml(s.attributes.friendly_name)} (${
                  Number.isNaN(parseFloat(s.state))
                    ? "?"
                    : parseFloat(s.state).toFixed(0)
                } km)</option>`
            )
            .join("")}
        </select>
        <span class="pv-picker-status"></span>
      </div>`;
  }

  _wireStatusStrip(strip) {
    const openPark = (placeId) => {
      const match = Object.values(this._hass.states).find(
        (s) => s.attributes.source === this.config.source && s.attributes.place_id === placeId
      );
      if (match) this._openPark(match.entity_id);
    };

    const last = strip.querySelector(".pv-open-last");
    if (last) last.addEventListener("click", () => openPark(last.dataset.place));
    const nextView = strip.querySelector(".pv-open-next");
    if (nextView) nextView.addEventListener("click", () => openPark(nextView.dataset.place));

    const pick = strip.querySelector(".pv-pick-next");
    if (pick) {
      pick.addEventListener("click", () => {
        this._pickerOpen = !this._pickerOpen;
        this._stripSignature = null;
        this._renderStatusStrip();
      });
    }

    const clear = strip.querySelector(".pv-clear-next");
    if (clear) {
      clear.addEventListener("click", async () => {
        await this._hass.callService("park_visits", "clear_next_park", {});
        this._stripSignature = null;
      });
    }

    const select = strip.querySelector(".pv-picker-select");
    if (select) {
      select.addEventListener("change", async () => {
        if (!select.value) return;
        const status = strip.querySelector(".pv-picker-status");
        status.textContent = "Saving…";
        try {
          await this._hass.callService("park_visits", "set_next_park", {
            place_id: select.value,
          });
          this._pickerOpen = false;
          this._stripSignature = null;
          this._renderStatusStrip();
        } catch (err) {
          status.textContent = `Couldn't set: ${err && err.message ? err.message : err}`;
        }
      });
    }
  }

  /**
   * Everything the open dialog actually displays.
   *
   * Home Assistant assigns .hass on *every* state change anywhere in the
   * system — dozens of times a minute on a busy instance — and the dialog is
   * rendered by replacing innerHTML. Redrawing on each of those pushes reset
   * the scroll position and destroyed anything typed into the review form,
   * so a redraw now only happens when one of these values has changed.
   */
  _dialogSignature() {
    const state = this._hass && this._hass.states[this._openEntity];
    if (!state) return "missing";
    const a = state.attributes;
    return [
      state.last_updated,
      a.friendly_name,
      a.our_rating,
      a.our_liked,
      a.our_disliked,
      a.our_note,
      a.our_photo_count,
      a.our_reviewed_at,
      this._details ? "details" : "nodetails",
      this._detailsError ? "err" : "ok",
      (this._googlePhotoUrls || []).length,
      (this._ourPhotoUrls || []).length,
      this._formOpen ? "form" : "noform",
      this._pendingReview ? JSON.stringify(this._pendingReview) : "-",
      // So the "Set as next visit" button reflects the current selection.
      this._isNextPark(a.place_id) ? "next" : "notnext",
    ].join("|");
  }

  /**
   * Entity attributes, with a just-saved (or just-deleted) review overlaid.
   *
   * Saving is a service call; the updated entity state arrives moments later
   * on the next hass push. Rendering straight from the entity in that gap
   * would flash "We haven't reviewed this park yet" at someone who has just
   * written a review, so the submitted values stand in until the real state
   * catches up.
   */
  _effectiveAttributes(state) {
    const a = state.attributes;
    const pending = this._pendingReview;
    if (!pending || pending.placeId !== a.place_id) return a;

    const caughtUp = pending.cleared
      ? a.our_reviewed_at == null
      : a.our_reviewed_at != null && Number(a.our_rating) === Number(pending.rating);
    if (caughtUp) {
      this._pendingReview = null;
      return a;
    }

    return pending.cleared
      ? {
          ...a,
          our_rating: null,
          our_liked: "",
          our_disliked: "",
          our_note: "",
          our_reviewed_at: null,
          our_photo_count: 0,
        }
      : { ...a, ...pending.values };
  }

  _isNextPark(placeId) {
    const next = this._sensorByRole("next_park");
    return !!(placeId && next && next.attributes.place_id === placeId);
  }

  _maybeRerenderDialog() {
    // Never redraw underneath someone who is mid-review: even a "relevant"
    // change isn't worth discarding half-written text.
    if (this._formOpen) return;
    if (this._dialogSignature() === this._renderedSignature) return;
    this._renderDialog();
  }

  /* ---------------------------------------------------------------- build */

  _build() {
    if (this._built || !this.config) return;
    this._built = true;

    this.innerHTML = `
      <ha-card header="${escapeHtml(this.config.title)}">
        <div class="card-content">
          <div class="pv-status-strip"></div>
          ${
            this.config.show_filter
              ? `<input class="pv-filter" type="search" placeholder="Filter parks…" />`
              : ""
          }
          <div class="pv-scroll">
            <table class="pv-table">
              <thead><tr>${COLUMNS.map((c) =>
                c.sortable === false
                  ? `<th class="pv-nosort"></th>`
                  : `<th data-key="${c.key}" title="Sort by ${escapeHtml(
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
      <div class="pv-dialog-root"></div>
      ${STYLES}
    `;

    this.querySelectorAll("th[data-key]").forEach((th) => {
      th.addEventListener("click", () => this._onHeaderClick(th.dataset.key));
    });
    const filterEl = this.querySelector(".pv-filter");
    if (filterEl) {
      filterEl.addEventListener("input", (e) => {
        this._filter = e.target.value.trim().toLowerCase();
        this._signature = null;
        this._renderRows();
      });
    }
    // Delegated so they survive every tbody rebuild.
    this.querySelector("tbody").addEventListener("click", (ev) => {
      const button = ev.target.closest(".pv-rowbtn");
      if (button) {
        ev.preventDefault();
        this._openPark(button.dataset.entity, { straightToForm: true });
        return;
      }
      const link = ev.target.closest(".pv-name");
      if (!link) return;
      ev.preventDefault();
      this._openPark(link.dataset.entity);
    });

    this._renderRows();
    this._renderStatusStrip();
  }

  /* --------------------------------------------------------------- table */

  _onHeaderClick(key) {
    if (!key) return;
    if (this._sortKey === key) {
      this._sortDir = this._sortDir === "asc" ? "desc" : "asc";
    } else {
      this._sortKey = key;
      this._sortDir = "asc";
    }
    this._signature = null;
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

    // Redrawing 100 rows on every state push is wasteful; skip when nothing
    // that affects this table has changed.
    const signature = `${this._sortKey}|${this._sortDir}|${this._filter}|${rows.length}|${rows
      .map((s) => `${s.entity_id}:${s.last_updated}`)
      .join(",")}`;
    if (signature === this._signature) return;
    this._signature = signature;

    this.querySelector("tbody").innerHTML = rows
      .map(
        (s) =>
          `<tr>${COLUMNS.map(
            (c) => `<td class="${c.numeric ? "num" : ""}">${c.display(s)}</td>`
          ).join("")}</tr>`
      )
      .join("");

    this.querySelectorAll("th").forEach((th) => {
      const arrow = th.querySelector(".pv-arrow");
      if (arrow) {
        arrow.textContent =
          th.dataset.key === this._sortKey ? (this._sortDir === "asc" ? "▲" : "▼") : "";
      }
    });

    const countEl = this.querySelector(".pv-count");
    if (countEl) {
      const col = COLUMNS.find((c) => c.key === this._sortKey);
      countEl.textContent = `${rows.length} park${rows.length === 1 ? "" : "s"} — sorted by ${
        col ? col.label : this._sortKey
      } (${this._sortDir === "asc" ? "ascending" : "descending"})`;
    }
  }

  /* -------------------------------------------------------------- dialog */

  async _openPark(entityId, { straightToForm = false } = {}) {
    this._openEntity = entityId;
    this._details = null;
    this._detailsError = null;
    // The form is a separate popup that takes the place of the detail view,
    // rather than a panel appended under Google's reviews.
    this._formOpen = straightToForm;
    this._photoItems = [];
    this._lightboxIndex = null;
    this._renderDialog();

    const state = this._hass.states[entityId];
    const placeId = state && state.attributes.place_id;
    if (!placeId) {
      this._detailsError = "This park has no place_id, so Google details can't be loaded.";
      this._renderDialog();
      return;
    }

    try {
      this._details = await this._hass.callApi("GET", `park_visits/details/${placeId}`);
    } catch (err) {
      // Details are a bonus — our own review still renders without them.
      this._detailsError =
        "Couldn't load Google details for this park. Our own review is still shown below.";
    }
    await this._loadPhotoUrls(placeId);
    this._renderDialog();
  }

  async _loadPhotoUrls(placeId) {
    // <img> can't send an auth header, so ask HA to sign each media path.
    const sign = async (path) => {
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
    };

    this._googlePhotoUrls = [];
    const count = (this._details && this._details.photo_count) || 0;
    for (let i = 0; i < count; i++) {
      const url = await sign(`/api/park_visits/google_photo/${placeId}/${i}`);
      if (url) this._googlePhotoUrls.push(url);
    }

    this._ourPhotoUrls = [];
    // Filenames come from the details endpoint, which reads them live from
    // the review store (so a just-uploaded photo appears immediately).
    const filenames = (this._details && this._details.our_photos) || [];
    for (const filename of filenames) {
      const url = await sign(`/api/park_visits/photo/${placeId}/${filename}`);
      if (url) this._ourPhotoUrls.push({ filename, url });
    }
  }

  _closeDialog() {
    this._openEntity = null;
    this._details = null;
    this._googlePhotoUrls = [];
    this._ourPhotoUrls = [];
    this._formOpen = false;
    this._renderedSignature = null;
    this._pendingReview = null;
    this._photoItems = [];
    this._lightboxIndex = null;
    this.querySelector(".pv-dialog-root").innerHTML = "";
  }

  _openLightbox(index) {
    this._lightboxIndex = index;
    this._renderDialog();
  }

  _closeLightbox() {
    this._lightboxIndex = null;
    this._renderDialog();
  }

  _lightboxHtml() {
    const items = this._photoItems || [];
    const item = this._lightboxIndex != null ? items[this._lightboxIndex] : null;
    if (!item) return "";
    const many = items.length > 1;
    return `
      <div class="pv-lb-backdrop">
        <div class="pv-lb-dialog" role="dialog" aria-modal="true">
          <button class="pv-lb-close" title="Close">✕</button>
          <img class="pv-lb-full" src="${escapeHtml(item.url)}" alt="">
          <div class="pv-lb-nav">
            ${many ? `<button class="pv-lb-prev">‹ Previous</button>` : ""}
            <span class="muted">${escapeHtml(item.source)}${
      many ? ` · ${this._lightboxIndex + 1} of ${items.length}` : ""
    }</span>
            ${many ? `<button class="pv-lb-next">Next ›</button>` : ""}
          </div>
        </div>
      </div>`;
  }

  _renderDialog() {
    const root = this.querySelector(".pv-dialog-root");
    if (!root) return;
    if (!this._openEntity) {
      root.innerHTML = "";
      this._renderedSignature = null;
      return;
    }
    const state = this._hass.states[this._openEntity];
    if (!state) {
      root.innerHTML = "";
      this._renderedSignature = null;
      return;
    }
    // The backdrop is the scroll container; a redraw would otherwise jump the
    // reader back to the top of a long park page.
    const previousBackdrop = root.querySelector(".pv-backdrop");
    const previousScroll = previousBackdrop ? previousBackdrop.scrollTop : 0;
    const a = this._effectiveAttributes(state);
    const d = this._details;

    // Combined so a click can open one lightbox that pages through every
    // photo shown on this park — our uploads first, then Google's, matching
    // the order they appear in the page below.
    this._photoItems = [
      ...(this._ourPhotoUrls || []).map((p) => ({ url: p.url, source: "Our photo" })),
      ...(this._googlePhotoUrls || []).map((u) => ({ url: u, source: "Google photo" })),
    ];
    const ourCount = (this._ourPhotoUrls || []).length;
    const ourPhotos = (this._ourPhotoUrls || [])
      .map(
        (p, i) =>
          `<img class="pv-photo pv-photo-click" data-index="${i}" src="${escapeHtml(
            p.url
          )}" loading="lazy" alt="">`
      )
      .join("");
    const googlePhotos = (this._googlePhotoUrls || [])
      .map(
        (u, i) =>
          `<img class="pv-photo pv-photo-click" data-index="${
            ourCount + i
          }" src="${escapeHtml(u)}" loading="lazy" alt="">`
      )
      .join("");

    const googleReviews = d && d.reviews && d.reviews.length
      ? d.reviews
          .map(
            (r) => `
            <div class="pv-review">
              <div class="pv-review-head">
                <strong>${escapeHtml(r.author)}</strong>
                <span class="muted">${r.rating != null ? "★ " + r.rating : ""} ${escapeHtml(
              r.relative_time || ""
            )}</span>
              </div>
              <div class="pv-review-text">${escapeHtml(r.text || "")}</div>
            </div>`
          )
          .join("")
      : `<div class="muted">${
          d ? "Google has no written reviews for this park." : "Loading…"
        }</div>`;

    const hasOurReview = a.our_reviewed_at != null;
    const ourReview = hasOurReview
      ? `
        <div class="pv-ourreview">
          <div><strong>Our rating:</strong> ${escapeHtml(a.our_rating)}/10</div>
          ${a.our_liked ? `<div><strong>Liked:</strong> ${escapeHtml(a.our_liked)}</div>` : ""}
          ${
            a.our_disliked
              ? `<div><strong>Didn't like:</strong> ${escapeHtml(a.our_disliked)}</div>`
              : ""
          }
          ${a.our_note ? `<div><strong>Notes:</strong> ${escapeHtml(a.our_note)}</div>` : ""}
          <div class="muted pv-when">Reviewed ${escapeHtml(
            new Date(a.our_reviewed_at).toLocaleString()
          )}</div>
        </div>`
      : `<div class="muted">We haven't reviewed this park yet.</div>`;

    const title = escapeHtml(a.friendly_name || state.entity_id);
    const body = this._formOpen
      ? this._formHtml(a, hasOurReview)
      : `
            <div class="pv-meta">
              ${
                a.rating != null
                  ? `<span class="pv-big">★ ${Number(a.rating).toFixed(1)}</span>
                     <span class="muted">(${a.rating_count || 0} Google reviews)</span>`
                  : `<span class="muted">No Google rating</span>`
              }
              <span class="muted"> · ${escapeHtml(
                Number.isNaN(parseFloat(state.state))
                  ? ""
                  : parseFloat(state.state).toFixed(1) + " km away"
              )}</span>
            </div>
            <div class="categories">${(a.categories || [])
              .map((c) => `<span class="chip">${escapeHtml(c)}</span>`)
              .join("")}</div>
            <div class="pv-address">${escapeHtml(a.address || "")}</div>
            ${d && d.summary ? `<p class="pv-summary">${escapeHtml(d.summary)}</p>` : ""}
            ${
              this._detailsError
                ? `<div class="pv-warn">${escapeHtml(this._detailsError)}</div>`
                : ""
            }
            <div class="pv-links">
              ${
                a.google_maps_uri
                  ? `<a href="${escapeHtml(
                      a.google_maps_uri
                    )}" target="_blank" rel="noopener">Google Maps ↗</a>`
                  : ""
              }
              ${
                d && d.website
                  ? `<a href="${escapeHtml(
                      d.website
                    )}" target="_blank" rel="noopener">Website ↗</a>`
                  : ""
              }
              ${d && d.phone ? `<span class="muted">${escapeHtml(d.phone)}</span>` : ""}
            </div>

            <div class="pv-actions">
              <button class="pv-btn pv-write">${
                hasOurReview ? "Edit our review" : "Write a review"
              }</button>
              <button class="pv-btn pv-secondary pv-set-next">${
                this._isNextPark(a.place_id) ? "✓ Next up" : "Set as next visit"
              }</button>
            </div>

            <h3>Our review</h3>
            ${ourReview}
            ${ourPhotos ? `<div class="pv-photos">${ourPhotos}</div>` : ""}

            ${
              googlePhotos
                ? `<h3>Photos from Google</h3><div class="pv-photos">${googlePhotos}</div>`
                : ""
            }

            <h3>Reviews from Google</h3>
            ${googleReviews}`;

    root.innerHTML = `
      <div class="pv-backdrop">
        <div class="pv-dialog" role="dialog" aria-modal="true">
          <div class="pv-dialog-head">
            <h2>${this._formOpen ? `${hasOurReview ? "Edit" : "Write"} review — ${title}` : title}</h2>
            <button class="pv-close" title="Close">✕</button>
          </div>
          <div class="pv-dialog-body">${body}</div>
        </div>
      </div>
      ${this._lightboxHtml()}
    `;

    const backdrop = root.querySelector(".pv-backdrop");
    if (backdrop && previousScroll) backdrop.scrollTop = previousScroll;
    this._renderedSignature = this._dialogSignature();

    // A signed photo URL can still fail (Google details fell out of the
    // server-side cache, or one of our files went missing). Drop dead
    // thumbnails rather than leaving grey boxes — but keep any that carry a
    // delete button, otherwise a missing file would leave an entry in the
    // review that can never be cleared.
    root.querySelectorAll(".pv-photo").forEach((img) => {
      img.addEventListener("error", () => {
        const wrapper = img.closest(".pv-photo-wrap");
        if (wrapper && wrapper.querySelector(".pv-photo-del")) {
          img.remove();
          wrapper.classList.add("pv-photo-broken");
          wrapper.setAttribute("title", "This photo file is missing");
          return;
        }
        (wrapper || img).remove();
        root.querySelectorAll(".pv-photos").forEach((strip) => {
          if (!strip.querySelector(".pv-photo, .pv-photo-broken")) strip.remove();
        });
      });
    });

    root.querySelector(".pv-close").addEventListener("click", () => this._closeDialog());
    root.querySelector(".pv-backdrop").addEventListener("click", (ev) => {
      if (ev.target.classList.contains("pv-backdrop")) this._closeDialog();
    });

    root.querySelectorAll(".pv-photo-click").forEach((img) => {
      img.addEventListener("click", () =>
        this._openLightbox(parseInt(img.dataset.index, 10))
      );
    });
    const lbClose = root.querySelector(".pv-lb-close");
    if (lbClose) lbClose.addEventListener("click", () => this._closeLightbox());
    const lbBackdrop = root.querySelector(".pv-lb-backdrop");
    if (lbBackdrop) {
      lbBackdrop.addEventListener("click", (ev) => {
        if (ev.target.classList.contains("pv-lb-backdrop")) this._closeLightbox();
      });
    }
    const lbPrev = root.querySelector(".pv-lb-prev");
    if (lbPrev)
      lbPrev.addEventListener("click", () => {
        const items = this._photoItems || [];
        this._openLightbox((this._lightboxIndex - 1 + items.length) % items.length);
      });
    const lbNext = root.querySelector(".pv-lb-next");
    if (lbNext)
      lbNext.addEventListener("click", () => {
        const items = this._photoItems || [];
        this._openLightbox((this._lightboxIndex + 1) % items.length);
      });

    const write = root.querySelector(".pv-write");
    if (write) {
      write.addEventListener("click", () => {
        this._formOpen = true;
        this._renderDialog();
      });
    }

    const setNext = root.querySelector(".pv-set-next");
    if (setNext) {
      setNext.addEventListener("click", async () => {
        const alreadyNext = this._isNextPark(a.place_id);
        setNext.disabled = true;
        try {
          await this._hass.callService(
            "park_visits",
            alreadyNext ? "clear_next_park" : "set_next_park",
            alreadyNext ? {} : { place_id: a.place_id }
          );
          this._stripSignature = null;
          this._renderedSignature = null;
          this._renderDialog();
        } catch (err) {
          setNext.disabled = false;
        }
      });
    }

    const form = root.querySelector(".pv-form");
    if (form) this._wireForm(form, a, hasOurReview);
  }

  _formHtml(a, hasOurReview) {
    // Existing photos get their own delete buttons; removing one is immediate
    // and separate from saving the text fields.
    const existing = (this._ourPhotoUrls || [])
      .map(
        (p) => `
        <div class="pv-photo-wrap">
          <img class="pv-photo" src="${escapeHtml(p.url)}" loading="lazy" alt="">
          <button type="button" class="pv-photo-del" data-filename="${escapeHtml(
            p.filename
          )}" title="Delete this photo">✕</button>
        </div>`
      )
      .join("");

    return `
      <form class="pv-form">
        <label>Rating (0–10)</label>
        <input type="number" name="rating" min="0" max="10" step="0.5"
               value="${escapeHtml(a.our_rating ?? "")}" required>
        <label>What we liked</label>
        <textarea name="liked" rows="3">${escapeHtml(a.our_liked || "")}</textarea>
        <label>What we didn't like</label>
        <textarea name="disliked" rows="3">${escapeHtml(a.our_disliked || "")}</textarea>
        <label>Other notes</label>
        <textarea name="note" rows="3">${escapeHtml(a.our_note || "")}</textarea>
        ${existing ? `<label>Photos</label><div class="pv-photos">${existing}</div>` : ""}
        <label>Add a photo</label>
        <input type="file" name="photo" accept="image/*">
        <div class="pv-form-actions">
          <button type="submit" class="pv-btn">Save review</button>
          <button type="button" class="pv-btn pv-secondary pv-cancel">Cancel</button>
          ${
            hasOurReview
              ? `<button type="button" class="pv-btn pv-danger pv-delete">Delete review</button>`
              : ""
          }
          <span class="pv-status"></span>
        </div>
      </form>`;
  }

  _wireForm(form, attrs, hasOurReview) {
    const status = form.querySelector(".pv-status");
    const placeId = attrs.place_id;

    form.querySelector(".pv-cancel").addEventListener("click", () => {
      this._formOpen = false;
      this._renderDialog();
    });

    const deleteButton = form.querySelector(".pv-delete");
    if (deleteButton) {
      deleteButton.addEventListener("click", async () => {
        if (this._busy) return;
        // Deleting also removes the photo files from disk, so make that plain
        // before doing it.
        const photoCount = (this._ourPhotoUrls || []).length;
        const warning = photoCount
          ? `Delete our review and ${photoCount} uploaded photo${
              photoCount === 1 ? "" : "s"
            }? This can't be undone.`
          : "Delete our review? This can't be undone.";
        if (!window.confirm(warning)) return;

        this._busy = true;
        status.textContent = "Deleting…";
        status.className = "pv-status";
        try {
          await this._hass.callService("park_visits", "delete_review", {
            place_id: placeId,
          });
          this._pendingReview = { placeId, cleared: true };
          this._formOpen = false;
          this._ourPhotoUrls = [];
          await this._reloadDetails(placeId);
          this._renderDialog();
        } catch (err) {
          status.textContent = `Couldn't delete: ${err && err.message ? err.message : err}`;
          status.classList.add("err");
        } finally {
          this._busy = false;
        }
      });
    }

    form.querySelectorAll(".pv-photo-del").forEach((button) => {
      button.addEventListener("click", async () => {
        if (this._busy) return;
        if (!window.confirm("Delete this photo? This can't be undone.")) return;
        this._busy = true;
        status.textContent = "Deleting photo…";
        status.className = "pv-status";
        try {
          await this._hass.callService("park_visits", "delete_photo", {
            place_id: placeId,
            filename: button.dataset.filename,
          });
          await this._reloadDetails(placeId);
          this._renderDialog();
        } catch (err) {
          status.textContent = `Couldn't delete photo: ${
            err && err.message ? err.message : err
          }`;
          status.classList.add("err");
        } finally {
          this._busy = false;
        }
      });
    });

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (this._busy) return;
      this._busy = true;
      status.textContent = "Saving…";
      status.className = "pv-status";

      const submitted = {
        rating: parseFloat(form.rating.value),
        liked: form.liked.value,
        disliked: form.disliked.value,
        note: form.note.value,
      };

      try {
        await this._hass.callService("park_visits", "rate_park", {
          place_id: placeId,
          ...submitted,
        });
        this._pendingReview = {
          placeId,
          rating: submitted.rating,
          values: {
            our_rating: submitted.rating,
            our_liked: submitted.liked,
            our_disliked: submitted.disliked,
            our_note: submitted.note,
            our_reviewed_at: new Date().toISOString(),
          },
        };

        const file = form.photo.files && form.photo.files[0];
        if (file) {
          status.textContent = "Uploading photo…";
          await this._uploadPhoto(placeId, file);
        }

        status.textContent = "Saved ✓";
        status.classList.add("ok");
        this._formOpen = false;
        await this._reloadDetails(placeId);
        this._renderDialog();
      } catch (err) {
        status.textContent = `Couldn't save: ${err && err.message ? err.message : err}`;
        status.classList.add("err");
      } finally {
        this._busy = false;
      }
    });
  }

  async _reloadDetails(placeId) {
    // Re-read details to pick up the current photo list. The Google half of
    // the response comes from the 24h server-side cache, so this costs no
    // API quota.
    try {
      this._details = await this._hass.callApi("GET", `park_visits/details/${placeId}`);
      await this._loadPhotoUrls(placeId);
    } catch (err) {
      /* keep whatever we already had */
    }
  }

  async _uploadPhoto(placeId, file) {
    // Multipart, so this goes out as a raw fetch rather than callApi (which
    // is JSON-only). The auth token comes from the hass object.
    const body = new FormData();
    body.append("photo", file, file.name);
    const response = await fetch(`/api/park_visits/upload/${placeId}`, {
      method: "POST",
      body,
      headers: { Authorization: `Bearer ${this._hass.auth.data.access_token}` },
    });
    if (!response.ok) {
      let detail = `${response.status}`;
      try {
        const payload = await response.json();
        if (payload && payload.message) detail = payload.message;
      } catch (e) {
        /* non-JSON error body */
      }
      throw new Error(detail);
    }
    return response.json();
  }

  getCardSize() {
    return 12;
  }
}

const STYLES = `
<style>
  .pv-strip { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
  .pv-strip-box {
    flex: 1 1 240px; padding: 10px 12px; border-radius: 10px;
    background: var(--secondary-background-color, #222);
    border: 1px solid var(--divider-color, #333);
  }
  .pv-strip-next { border-color: var(--primary-color, #03a9f4); }
  .pv-strip-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    opacity: 0.7; margin-bottom: 4px;
  }
  .pv-strip-name { font-size: 16px; font-weight: 600; }
  .pv-strip-sub { font-size: 12px; opacity: 0.75; margin-top: 2px; }
  .pv-strip-empty { font-size: 13px; opacity: 0.6; }
  .pv-strip-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .pv-strip-btn {
    padding: 3px 10px; border-radius: 6px; cursor: pointer; font: inherit; font-size: 12px;
    border: 1px solid var(--divider-color, #444);
    background: transparent; color: var(--primary-text-color, #eee);
  }
  .pv-strip-btn:hover {
    border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4);
  }
  .pv-picker { margin-top: 8px; display: flex; gap: 8px; align-items: center; }
  .pv-picker-select {
    flex: 1; padding: 5px; border-radius: 6px; font: inherit;
    border: 1px solid var(--divider-color, #333);
    background: var(--primary-background-color, #111); color: var(--primary-text-color, #eee);
  }
  .pv-picker-status { font-size: 12px; opacity: 0.75; }
  .pv-scroll { overflow-x: auto; }
  .pv-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .pv-table th, .pv-table td {
    text-align: left; padding: 8px 10px;
    border-bottom: 1px solid var(--divider-color, #333); vertical-align: top;
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
  .pv-name { color: var(--primary-color, #03a9f4); text-decoration: none; cursor: pointer; }
  .pv-name:hover { text-decoration: underline; }
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

  .pv-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    display: flex; align-items: flex-start; justify-content: center;
    z-index: 9999; padding: 24px 12px; overflow-y: auto;
  }
  .pv-dialog {
    background: var(--card-background-color, #1c1c1c);
    color: var(--primary-text-color, #eee);
    border-radius: var(--ha-card-border-radius, 12px);
    max-width: 680px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  }
  .pv-dialog-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; border-bottom: 1px solid var(--divider-color, #333);
    position: sticky; top: 0; background: inherit; border-radius: inherit;
  }
  .pv-dialog-head h2 { margin: 0; font-size: 18px; }
  .pv-close {
    background: none; border: none; color: inherit; font-size: 18px;
    cursor: pointer; opacity: 0.7;
  }
  .pv-close:hover { opacity: 1; }
  .pv-dialog-body { padding: 16px; }
  .pv-dialog-body h3 {
    margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
    letter-spacing: 0.04em; opacity: 0.7;
  }
  .pv-big { font-size: 20px; font-weight: 600; }
  .pv-address { font-size: 13px; opacity: 0.8; margin-top: 4px; }
  .pv-summary { font-size: 14px; margin: 8px 0 0; }
  .pv-links { display: flex; gap: 14px; margin-top: 8px; font-size: 13px; flex-wrap: wrap; }
  .pv-links a { color: var(--primary-color, #03a9f4); }
  .pv-warn {
    margin-top: 10px; padding: 8px 10px; border-radius: 6px; font-size: 13px;
    background: var(--secondary-background-color, #2a2a2a);
  }
  .pv-photos { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
  .pv-photo {
    height: 130px; border-radius: 8px; object-fit: cover; flex: 0 0 auto;
    background: var(--secondary-background-color, #2a2a2a);
  }
  .pv-photo-click { cursor: pointer; }
  .pv-photo-click:hover { filter: brightness(1.08); }
  .pv-review { padding: 8px 0; border-bottom: 1px solid var(--divider-color, #2a2a2a); }
  .pv-review:last-child { border-bottom: none; }
  .pv-review-head { display: flex; gap: 8px; justify-content: space-between; font-size: 13px; }
  .pv-review-text { font-size: 14px; margin-top: 4px; white-space: pre-wrap; }
  .pv-ourreview { font-size: 14px; display: flex; flex-direction: column; gap: 4px; }
  .pv-when { font-size: 12px; }
  .pv-actions { margin-top: 16px; }
  .pv-btn {
    padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font: inherit;
    background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff);
  }
  .pv-form { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; }
  .pv-form label { font-size: 12px; opacity: 0.75; }
  .pv-form input[type=number], .pv-form textarea, .pv-form input[type=file] {
    width: 100%; box-sizing: border-box; padding: 6px; font: inherit;
    border-radius: 6px; border: 1px solid var(--divider-color, #333);
    background: var(--primary-background-color, #111); color: var(--primary-text-color, #eee);
  }
  .pv-form-actions {
    display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap;
  }
  .pv-status { font-size: 13px; }
  .pv-status.ok { color: var(--success-color, #4caf50); }
  .pv-status.err { color: var(--error-color, #f44336); }
  .pv-secondary {
    background: var(--secondary-background-color, #2a2a2a);
    color: var(--primary-text-color, #eee);
  }
  .pv-danger { background: var(--error-color, #f44336); margin-left: auto; }
  /* Matches .pv-btn (the "Write a review" button) so the two entry points
     into the review form look like the same action. */
  .pv-rowbtn {
    padding: 5px 14px; border: none; border-radius: 6px;
    background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff);
    cursor: pointer; font: inherit; font-size: 13px; white-space: nowrap;
  }
  .pv-rowbtn:hover { filter: brightness(1.1); }
  .pv-nosort { cursor: default; }
  .pv-photo-wrap { position: relative; flex: 0 0 auto; }
  .pv-photo-del {
    position: absolute; top: 4px; right: 4px; width: 22px; height: 22px;
    border: none; border-radius: 50%; cursor: pointer; line-height: 1;
    background: rgba(0,0,0,0.65); color: #fff; font-size: 12px;
  }
  .pv-photo-del:hover { background: var(--error-color, #f44336); }
  .pv-photo-broken {
    width: 130px; height: 130px; border-radius: 8px;
    background: var(--secondary-background-color, #2a2a2a);
    border: 1px dashed var(--divider-color, #444);
  }
  .pv-photo-broken::after {
    content: "missing"; display: flex; align-items: center; justify-content: center;
    height: 100%; font-size: 12px; opacity: 0.6;
  }
  .pv-lb-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.8);
    display: flex; align-items: center; justify-content: center;
    z-index: 10000; padding: 24px 12px;
  }
  .pv-lb-dialog {
    position: relative; max-width: 900px; width: 100%;
    background: var(--card-background-color, #1c1c1c);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.6); overflow: hidden;
  }
  .pv-lb-full { width: 100%; max-height: 78vh; object-fit: contain; background: #000; display: block; }
  .pv-lb-close {
    position: absolute; top: 8px; right: 8px; width: 30px; height: 30px;
    border: none; border-radius: 50%; cursor: pointer; line-height: 1;
    background: rgba(0,0,0,0.65); color: #fff; font-size: 15px;
  }
  .pv-lb-close:hover { background: var(--error-color, #f44336); }
  .pv-lb-nav {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 12px 16px;
  }
  .pv-lb-nav button {
    padding: 6px 14px; border: 1px solid var(--divider-color, #333); border-radius: 6px;
    background: var(--secondary-background-color, #2a2a2a);
    color: var(--primary-text-color, #eee); cursor: pointer; font: inherit;
  }
  .pv-lb-nav button:hover { border-color: var(--primary-color, #03a9f4); }
</style>`;

customElements.define("park-visits-table-card", ParkVisitsTableCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "park-visits-table-card",
  name: "Park Visits Table",
  description: "Sortable park table with detail panel, Google reviews and our own review form.",
});
