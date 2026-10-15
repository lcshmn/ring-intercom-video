/*
 * Ring Intercom ding history card.
 *
 * Shows the latest ding's picture and a timeline of recent dings, grouped by
 * day, from sensor.<name>_ding_history (ding history must be enabled).
 *
 * The pictures live under /media, which needs authentication. The sensor lists
 * them as media-source URIs; the card resolves each into a short-lived signed
 * URL through Home Assistant's media_source/resolve_media, so nothing has to
 * be made public.
 *
 *   type: custom:ring-ding-history-card
 *   entity: sensor.hauseingang_ding_history
 *   # optional:
 *   image_entity: image.hauseingang_last_ding    # default: derived from entity
 *   camera_entity: camera.hauseingang_camera     # "Live" button; default: derived
 *   title: Hauseingang
 *   max_entries: 30
 */

const CARD_VERSION = "1.0.0";

// Signed media URLs are requested with this lifetime and renewed before expiry.
const URL_LIFETIME_S = 3600;
const URL_RENEW_MARGIN_MS = 5 * 60 * 1000;

const STRINGS = {
  de: {
    lastDing: "Zuletzt geklingelt",
    noDings: "Noch kein Klingeln aufgezeichnet",
    noPicture: "Kein Bild",
    today: "Heute",
    yesterday: "Gestern",
    live: "Live",
    dingsToday: (n) => (n === 1 ? "1× heute" : `${n}× heute`),
    historyOff:
      "Klingel-Verlauf ist nicht aktiv. In configuration.yaml unter ring_intercom_camera: history: ergänzen.",
    missing: (e) => `Entität nicht gefunden: ${e}`,
    close: "Schließen",
    newer: "Neueres",
    older: "Älteres",
  },
  en: {
    lastDing: "Last ding",
    noDings: "No dings recorded yet",
    noPicture: "No picture",
    today: "Today",
    yesterday: "Yesterday",
    live: "Live",
    dingsToday: (n) => `${n}× today`,
    historyOff:
      "Ding history is off. Add history: under ring_intercom_camera: in configuration.yaml.",
    missing: (e) => `Entity not found: ${e}`,
    close: "Close",
    newer: "Newer",
    older: "Older",
  },
};

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .header {
    display: flex; align-items: center; gap: 12px;
    padding: 16px 16px 12px;
  }
  .badge {
    flex: none; width: 40px; height: 40px; border-radius: 50%;
    display: grid; place-items: center;
    background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.15);
    color: var(--primary-color);
  }
  .heading { flex: 1; min-width: 0; }
  .title {
    font-size: 16px; font-weight: 500; line-height: 20px;
    color: var(--primary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .subtitle {
    font-size: 13px; line-height: 18px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .count {
    flex: none; font-size: 12px; font-weight: 500; padding: 4px 10px;
    border-radius: 12px; color: var(--primary-color);
    background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12);
  }
  .hero {
    position: relative; margin: 0 16px; border-radius: 12px; overflow: hidden;
    aspect-ratio: 5 / 4; background: var(--secondary-background-color, #222);
  }
  .hero img {
    width: 100%; height: 100%; object-fit: cover; display: block; cursor: zoom-in;
  }
  .hero .empty {
    position: absolute; inset: 0; display: grid; place-items: center;
    align-content: center; gap: 8px; color: var(--secondary-text-color);
    font-size: 14px; text-align: center; padding: 16px;
  }
  .hero .empty ha-icon { --mdc-icon-size: 40px; opacity: 0.6; }
  .overlay {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 24px 14px 10px;
    background: linear-gradient(to top, rgba(0, 0, 0, 0.65), transparent);
    color: #fff; pointer-events: none;
  }
  .overlay .when { font-size: 15px; font-weight: 500; }
  .overlay .ago { font-size: 12px; opacity: 0.85; }
  .live {
    position: absolute; top: 10px; right: 10px;
    display: flex; align-items: center; gap: 4px;
    padding: 5px 10px 5px 8px; border: none; border-radius: 16px;
    background: rgba(0, 0, 0, 0.55); color: #fff;
    font: inherit; font-size: 12px; font-weight: 500; cursor: pointer;
  }
  .live ha-icon { --mdc-icon-size: 16px; }
  .live .dot {
    width: 7px; height: 7px; border-radius: 50%; background: #e53935;
  }
  .timeline { padding: 8px 0 12px; }
  .day {
    padding: 12px 16px 6px; font-size: 12px; font-weight: 500;
    letter-spacing: 0.04em; text-transform: uppercase;
    color: var(--secondary-text-color);
  }
  .row {
    display: flex; align-items: center; gap: 12px;
    padding: 6px 16px; cursor: default;
  }
  .row.has-image { cursor: pointer; }
  .row.has-image:hover { background: var(--secondary-background-color); }
  .thumb {
    flex: none; width: 64px; height: 51px; border-radius: 8px;
    object-fit: cover; background: var(--secondary-background-color, #222);
    display: grid; place-items: center; color: var(--secondary-text-color);
  }
  .thumb ha-icon { --mdc-icon-size: 20px; opacity: 0.6; }
  .row .text { flex: 1; min-width: 0; }
  .row .time { font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
  .row .meta { font-size: 12px; color: var(--secondary-text-color); }
  .message {
    padding: 16px; color: var(--secondary-text-color); font-size: 14px;
  }
  dialog {
    border: none; padding: 0; background: transparent; max-width: 96vw;
    max-height: 96vh; overflow: visible;
  }
  dialog::backdrop { background: rgba(0, 0, 0, 0.85); }
  .lightbox { position: relative; display: grid; gap: 10px; justify-items: center; }
  .lightbox img {
    max-width: 92vw; max-height: 80vh; border-radius: 12px; display: block;
  }
  .lightbox .caption { color: #fff; font-size: 15px; font-weight: 500; }
  .lightbox .controls { display: flex; gap: 8px; }
  .lightbox button {
    display: grid; place-items: center; width: 44px; height: 44px;
    border: none; border-radius: 50%; cursor: pointer;
    background: rgba(255, 255, 255, 0.15); color: #fff;
  }
  .lightbox button[disabled] { opacity: 0.3; cursor: default; }
`;

class RingDingHistoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._urls = new Map(); // media URI -> { url, renewAt }
    this._pending = new Set();
    this._signature = null;
    this._lightboxIndex = null;
  }

  static getStubConfig(hass) {
    const sensor = Object.keys(hass.states).find((id) =>
      /^sensor\..+_ding_history$/.test(id),
    );
    return { entity: sensor || "sensor.hauseingang_ding_history" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("entity (sensor.<name>_ding_history) is required");
    }
    const base = config.entity.replace(/^sensor\./, "").replace(/_ding_history$/, "");
    this._config = {
      max_entries: 30,
      image_entity: `image.${base}_last_ding`,
      camera_entity: `camera.${base}_camera`,
      ...config,
    };
    this._signature = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render when something the card shows changed; hass is set on
    // every state change anywhere in the instance.
    const signature = this._computeSignature();
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return 3 + Math.min(this._entries().length, 6);
  }

  connectedCallback() {
    // Keep "x minutes ago" current.
    this._timer = setInterval(() => this._render(), 60 * 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ---- data ----

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return STRINGS[lang] || STRINGS.en;
  }

  _entries() {
    const state = this._hass?.states[this._config?.entity];
    const entries = state?.attributes?.entries;
    return Array.isArray(entries) ? entries.slice(0, this._config.max_entries) : [];
  }

  _computeSignature() {
    if (!this._hass || !this._config) return null;
    const s = this._hass.states;
    const sensor = s[this._config.entity];
    const image = s[this._config.image_entity];
    return JSON.stringify([
      sensor?.state,
      sensor?.last_updated,
      image?.attributes?.entity_picture,
      Boolean(s[this._config.camera_entity]),
      this._hass.locale?.language,
    ]);
  }

  _mediaUrl(uri) {
    const cached = this._urls.get(uri);
    const now = Date.now();
    if (cached && cached.renewAt > now) return cached.url;
    if (!this._pending.has(uri)) {
      this._pending.add(uri);
      this._hass
        .callWS({
          type: "media_source/resolve_media",
          media_content_id: uri,
          expires: URL_LIFETIME_S,
        })
        .then((result) => {
          const url = this._hass.hassUrl ? this._hass.hassUrl(result.url) : result.url;
          this._urls.set(uri, {
            url,
            renewAt: Date.now() + URL_LIFETIME_S * 1000 - URL_RENEW_MARGIN_MS,
          });
          this._render();
        })
        .catch((err) => {
          // A picture deleted by retention between two updates, typically.
          console.warn("ring-ding-history-card: cannot resolve", uri, err);
          this._urls.set(uri, { url: null, renewAt: Date.now() + 60 * 1000 });
        })
        .finally(() => this._pending.delete(uri));
    }
    return cached?.url ?? null;
  }

  // ---- formatting ----

  _locale() {
    return this._hass?.locale?.language || this._hass?.language || undefined;
  }

  _formatTime(date) {
    return date.toLocaleTimeString(this._locale(), { hour: "2-digit", minute: "2-digit" });
  }

  _formatDay(date) {
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return this._t.today;
    if (date.toDateString() === yesterday.toDateString()) return this._t.yesterday;
    return date.toLocaleDateString(this._locale(), {
      weekday: "short", day: "2-digit", month: "2-digit",
    });
  }

  _formatAgo(date) {
    const rtf = new Intl.RelativeTimeFormat(this._locale(), { numeric: "auto" });
    // Calendar days, not 24 h blocks: 23:18 two evenings ago is "2 days ago"
    // even when that is only 27 hours back, matching the day headings.
    const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const days = Math.round((startOfDay(date) - startOfDay(new Date())) / 86400000);
    if (days !== 0) return rtf.format(days, "day");
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    if (Math.abs(seconds) < 60) return rtf.format(seconds, "second");
    if (Math.abs(seconds) < 3600) return rtf.format(Math.round(seconds / 60), "minute");
    return rtf.format(Math.round(seconds / 3600), "hour");
  }

  // ---- rendering ----

  _render() {
    if (!this._hass || !this._config) return;
    // Rebuilding the card would close the open lightbox; refresh only that,
    // and catch up when it closes.
    if (this.shadowRoot.querySelector("dialog")?.open) {
      this._dirty = true;
      this._renderLightbox();
      return;
    }
    this._dirty = false;
    const t = this._t;
    const states = this._hass.states;
    const sensor = states[this._config.entity];
    const root = this.shadowRoot;

    if (!sensor) {
      root.innerHTML = `<style>${STYLE}</style><ha-card><div class="message">${
        this._config.entity.startsWith("sensor.") && !states[this._config.image_entity]
          ? escapeHtml(t.historyOff)
          : escapeHtml(t.missing(this._config.entity))
      }</div></ha-card>`;
      return;
    }

    const entries = this._entries();
    const title =
      this._config.title ||
      (sensor.attributes.friendly_name || "").replace(/\s*Ding History$/i, "") ||
      "Ring";
    const last = entries[0] ? new Date(entries[0].time) : null;
    const todayCount = entries.filter(
      (e) => new Date(e.time).toDateString() === new Date().toDateString(),
    ).length;

    const imageState = states[this._config.image_entity];
    const heroUrl = imageState?.attributes?.entity_picture || null;
    const heroEntry = entries.find((e) => e.image);
    const heroDate = heroEntry ? new Date(heroEntry.time) : null;
    const hasCamera = Boolean(states[this._config.camera_entity]);

    let html = `<style>${STYLE}</style><ha-card>`;
    html += `
      <div class="header">
        <div class="badge"><ha-icon icon="mdi:doorbell-video"></ha-icon></div>
        <div class="heading">
          <div class="title">${escapeHtml(title)}</div>
          <div class="subtitle">${
            last ? `${escapeHtml(t.lastDing)} ${escapeHtml(this._formatAgo(last))}` : escapeHtml(t.noDings)
          }</div>
        </div>
        ${todayCount ? `<div class="count">${escapeHtml(t.dingsToday(todayCount))}</div>` : ""}
      </div>`;

    html += `<div class="hero">`;
    if (heroUrl && heroDate) {
      html += `
        <img src="${escapeAttr(heroUrl)}" alt="" data-open="hero">
        <div class="overlay">
          <div class="when">${escapeHtml(this._formatDay(heroDate))}, ${escapeHtml(this._formatTime(heroDate))}</div>
          <div class="ago">${escapeHtml(this._formatAgo(heroDate))}</div>
        </div>`;
    } else {
      html += `<div class="empty"><ha-icon icon="mdi:doorbell"></ha-icon>${escapeHtml(t.noDings)}</div>`;
    }
    if (hasCamera) {
      html += `<button class="live" data-live><span class="dot"></span>${escapeHtml(t.live)}</button>`;
    }
    html += `</div>`;

    if (entries.length) {
      html += `<div class="timeline">`;
      let currentDay = null;
      entries.forEach((entry, index) => {
        const date = new Date(entry.time);
        const day = this._formatDay(date);
        if (day !== currentDay) {
          currentDay = day;
          html += `<div class="day">${escapeHtml(day)}</div>`;
        }
        const url = entry.image ? this._mediaUrl(entry.image) : null;
        html += `<div class="row${entry.image ? " has-image" : ""}" ${
          entry.image ? `data-index="${index}"` : ""
        }>`;
        html += url
          ? `<img class="thumb" src="${escapeAttr(url)}" alt="" loading="lazy">`
          : `<div class="thumb"><ha-icon icon="${
              entry.image ? "mdi:image-outline" : "mdi:image-off-outline"
            }"></ha-icon></div>`;
        html += `
          <div class="text">
            <div class="time">${escapeHtml(this._formatTime(date))}</div>
            <div class="meta">${escapeHtml(entry.image ? this._formatAgo(date) : t.noPicture)}</div>
          </div></div>`;
      });
      html += `</div>`;
    }

    html += `<dialog></dialog></ha-card>`;
    root.innerHTML = html;

    root.querySelectorAll("[data-index]").forEach((el) =>
      el.addEventListener("click", () => this._openLightbox(Number(el.dataset.index))),
    );
    root.querySelector("[data-open=hero]")?.addEventListener("click", () =>
      this._openLightbox(entries.indexOf(heroEntry), heroUrl),
    );
    root.querySelector("[data-live]")?.addEventListener("click", () =>
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._config.camera_entity },
        }),
      ),
    );

  }

  _openLightbox(index, fallbackUrl = null) {
    this._lightboxIndex = index;
    this._lightboxFallback = fallbackUrl;
    this._renderLightbox();
  }

  _renderLightbox() {
    const dialog = this.shadowRoot.querySelector("dialog");
    if (!dialog) return;
    const entries = this._entries();
    const withImage = entries
      .map((entry, index) => ({ entry, index }))
      .filter(({ entry }) => entry.image);
    const pos = withImage.findIndex(({ index }) => index === this._lightboxIndex);
    if (pos < 0) {
      this._lightboxIndex = null;
      return;
    }
    const { entry } = withImage[pos];
    const date = new Date(entry.time);
    const url =
      this._mediaUrl(entry.image) || (pos === 0 ? this._lightboxFallback : null);
    const t = this._t;

    dialog.innerHTML = `
      <div class="lightbox">
        ${url ? `<img src="${escapeAttr(url)}" alt="">` : ""}
        <div class="caption">${escapeHtml(this._formatDay(date))}, ${escapeHtml(this._formatTime(date))}</div>
        <div class="controls">
          <button data-nav="-1" title="${escapeAttr(t.newer)}" ${pos === 0 ? "disabled" : ""}>
            <ha-icon icon="mdi:chevron-left"></ha-icon></button>
          <button data-close title="${escapeAttr(t.close)}"><ha-icon icon="mdi:close"></ha-icon></button>
          <button data-nav="1" title="${escapeAttr(t.older)}" ${
            pos === withImage.length - 1 ? "disabled" : ""
          }><ha-icon icon="mdi:chevron-right"></ha-icon></button>
        </div>
      </div>`;

    dialog.querySelectorAll("[data-nav]").forEach((btn) =>
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const next = withImage[pos + Number(btn.dataset.nav)];
        if (next) this._openLightbox(next.index);
      }),
    );
    const close = () => {
      this._lightboxIndex = null;
      dialog.close();
    };
    dialog.querySelector("[data-close]").addEventListener("click", close);
    dialog.onclick = (ev) => {
      if (ev.target === dialog) close();
    };
    dialog.onclose = () => {
      this._lightboxIndex = null;
      if (this._dirty) this._render();
    };
    if (!dialog.open) dialog.showModal();
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, "&#39;");
}

if (!customElements.get("ring-ding-history-card")) {
  customElements.define("ring-ding-history-card", RingDingHistoryCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ring-ding-history-card",
    name: "Ring Intercom ding history",
    description: "Latest ding picture and a timeline of recent dings.",
    preview: false,
  });
  console.info(`%c RING-DING-HISTORY-CARD %c ${CARD_VERSION} `, "color:#fff;background:#03a9f4", "");
}
