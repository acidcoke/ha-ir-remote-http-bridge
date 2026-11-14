/*
 * IR Remote Card - dashboard card of the "IR Remote HTTP Bridge" integration.
 *
 * Shows the SVG drawing of a remote. Elements carrying data-button="<id>"
 * are the keys. Normal mode sends the learned code, learn mode records one.
 */
const DOMAIN = "ir_remote_http_bridge";
const CARD_PREFIX = "ir-remote-card-";
const CACHE_KEY = `${DOMAIN}.cards`;

// card slug -> {entry_id, title}; one card type is registered per remote.
const REMOTES = new Map();
const INSTANCES = new Set();

const TEXTS = {
  en: {
    learn_mode: "Learn mode",
    done: "Done",
    pick_remote: "Select a remote in the card settings.",
    not_found: "Remote not found. Is the integration set up and loaded?",
    hint_learn: "Tap a key to learn its code.",
    learning: "Point the original remote at the IR blaster and press “{name}” … {s}s",
    learned: "“{name}” learned.",
    timeout: "No signal received for “{name}”.",
    busy: "The IR blaster is busy learning.",
    not_learned: "“{name}” has no code yet. Switch to learn mode.",
    failed: "Failed: {msg}",
    sent: "“{name}” sent.",
    selected: "“{name}” already has a code.",
    relearn: "Relearn",
    test: "Test",
    forget: "Delete",
    forgotten: "Code of “{name}” deleted.",
    progress: "{n} of {total} keys learned",
    remote: "Remote",
    title: "Title (optional)",
    max_height: "Maximum height in pixels",
    max_width: "Maximum width in pixels (optional)",
    allow_learning: "Show learn mode button",
  },
  de: {
    learn_mode: "Lernmodus",
    done: "Fertig",
    pick_remote: "Wähle in den Karteneinstellungen eine Fernbedienung aus.",
    not_found: "Fernbedienung nicht gefunden. Ist die Integration eingerichtet und geladen?",
    hint_learn: "Tippe auf eine Taste, um ihren Code zu lernen.",
    learning: "Originalfernbedienung auf den IR-Blaster richten und „{name}“ drücken … {s}s",
    learned: "„{name}“ gelernt.",
    timeout: "Kein Signal für „{name}“ empfangen.",
    busy: "Der IR-Blaster lernt gerade.",
    not_learned: "„{name}“ hat noch keinen Code. Wechsle in den Lernmodus.",
    failed: "Fehlgeschlagen: {msg}",
    sent: "„{name}“ gesendet.",
    selected: "„{name}“ hat bereits einen Code.",
    relearn: "Neu lernen",
    test: "Testen",
    forget: "Löschen",
    forgotten: "Code von „{name}“ gelöscht.",
    progress: "{n} von {total} Tasten gelernt",
    remote: "Fernbedienung",
    title: "Titel (optional)",
    max_height: "Maximale Höhe in Pixeln",
    max_width: "Maximale Breite in Pixeln (optional)",
    allow_learning: "Lernmodus-Schalter anzeigen",
  },
};

const STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; }
  .header {
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px; padding: 12px 12px 0 16px; min-height: 36px;
  }
  .title {
    font-size: 1.1em; font-weight: 500; color: var(--primary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  button {
    font: inherit; cursor: pointer; border-radius: 16px; padding: 5px 12px;
    border: 1px solid var(--divider-color, #8884); background: none;
    color: var(--primary-text-color); display: inline-flex; align-items: center;
    gap: 4px; white-space: nowrap;
  }
  button ha-icon { --mdc-icon-size: 18px; }
  button.active, button.primary {
    background: var(--primary-color); border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  button.danger { color: var(--error-color, #db4437); }
  button:disabled { opacity: 0.5; cursor: default; }
  .remote { padding: 12px 16px 4px; display: flex; justify-content: center; }
  .remote svg {
    width: 100%; height: auto; display: block;
    user-select: none; -webkit-user-select: none; touch-action: manipulation;
  }
  .remote [data-button] {
    cursor: pointer; transition: opacity 0.15s, filter 0.15s;
    -webkit-tap-highlight-color: transparent; outline: none;
  }
  .remote.use [data-button].unlearned { opacity: 0.3; }
  .remote.use [data-button].pressed { filter: brightness(1.7); }
  .remote.learn [data-button].learned {
    filter: drop-shadow(0 0 1.5px var(--success-color, #43a047))
            drop-shadow(0 0 1.5px var(--success-color, #43a047));
  }
  .remote.learn [data-button].unlearned {
    filter: drop-shadow(0 0 1.5px var(--warning-color, #ffa600))
            drop-shadow(0 0 1.5px var(--warning-color, #ffa600));
  }
  .remote.learn [data-button].selected {
    filter: drop-shadow(0 0 2px var(--primary-color))
            drop-shadow(0 0 3px var(--primary-color));
  }
  .remote.learn [data-button].learning {
    filter: drop-shadow(0 0 2px var(--primary-color))
            drop-shadow(0 0 4px var(--primary-color));
    animation: irb-pulse 1s ease-in-out infinite;
  }
  .remote.busy [data-button] { cursor: progress; }
  @keyframes irb-pulse { 50% { opacity: 0.35; } }
  @media (prefers-reduced-motion: reduce) {
    .remote.learn [data-button].learning { animation: none; }
  }
  .status {
    padding: 4px 16px 14px; min-height: 22px; text-align: center;
    color: var(--secondary-text-color); font-size: 0.9em; line-height: 1.4;
  }
  .status.error { color: var(--error-color, #db4437); }
  .status.success { color: var(--success-color, #43a047); }
  .actions { display: flex; justify-content: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .message { padding: 16px; color: var(--secondary-text-color); }
`;

class IrRemoteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._remote = null; // layout + svg from the backend
    this._learned = new Set();
    this._learning = null; // button id the blaster is waiting for
    this._learnMode = false;
    this._selected = null; // learned button picked in learn mode
    this._status = null; // {text, kind}
    this._loadedFor = null;
    this._unsub = null;
    this._timer = null;
    this._deadline = 0;
  }

  /** Card slug of the remote this card type belongs to (set by subclasses). */
  static get slug() {
    return null;
  }

  static getConfigForm() {
    return {
      schema: [
        ...(this.slug
          ? []
          : [{ name: "entry_id", required: true, selector: { config_entry: { integration: DOMAIN } } }]),
        { name: "title", selector: { text: {} } },
        { name: "max_height", selector: { number: { min: 200, max: 1600, step: 10, mode: "box" } } },
        { name: "max_width", selector: { number: { min: 120, max: 800, step: 10, mode: "box" } } },
        { name: "allow_learning", selector: { boolean: {} } },
      ],
      computeLabel: (schema, hass) => {
        const lang = TEXTS[(hass?.language || "en").split("-")[0]] || TEXTS.en;
        return { entry_id: lang.remote, title: lang.title, max_height: lang.max_height, max_width: lang.max_width,
                 allow_learning: lang.allow_learning }[schema.name];
      },
    };
  }

  static async getStubConfig(hass) {
    if (this.slug) return {};
    try {
      const remotes = await hass.callWS({ type: `${DOMAIN}/remotes` });
      if (remotes.length) return { entry_id: remotes[0].entry_id };
    } catch (err) { /* integration not ready */ }
    return { entry_id: "" };
  }

  setConfig(config) {
    this._rawConfig = config;
    this._config = { allow_learning: true, max_height: 650, ...config };
    const slug = this.constructor.slug;
    if (slug) this._config.entry_id = REMOTES.get(slug)?.entry_id || "";
    if (this._loadedFor !== this._config.entry_id) {
      this._reset();
      if (this._hass) this._load();
    }
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    const langChanged = this._hass && this._hass.language !== hass.language;
    this._hass = hass;
    if (first) this._load();
    else if (langChanged) this._render();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 3 };
  }

  connectedCallback() {
    INSTANCES.add(this);
    if (this._hass && this._remote && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    INSTANCES.delete(this);
    this._unsubscribe();
    this._stopTimer();
  }

  // ---------------------------------------------------------------- data

  _t(key, vars = {}) {
    const lang = (this._hass?.language || "en").split("-")[0];
    let text = (TEXTS[lang] || TEXTS.en)[key] || TEXTS.en[key] || key;
    for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, v);
    return text;
  }

  _name(buttonId) {
    const button = this._remote?.buttons.find((b) => b.id === buttonId);
    return button ? button.name : buttonId;
  }

  _reset() {
    this._unsubscribe();
    this._stopTimer();
    this._remote = null;
    this._learned = new Set();
    this._learning = null;
    this._learnMode = false;
    this._selected = null;
    this._status = null;
    this._loadedFor = null;
    this._error = null;
  }

  async _load() {
    const entryId = this._config.entry_id;
    if (!entryId || !this._hass) return;
    this._loadedFor = entryId;
    try {
      const remote = await this._hass.callWS({ type: `${DOMAIN}/remote`, entry_id: entryId });
      if (this._config.entry_id !== entryId) return;
      this._remote = remote;
      this._applyState(remote);
      this._render();
      if (this.isConnected) this._subscribe();
    } catch (err) {
      if (this._config.entry_id !== entryId) return;
      this._error = this._t("not_found");
      this._render();
    }
  }

  async _subscribe() {
    this._unsubscribe();
    const entryId = this._config.entry_id;
    try {
      const unsub = await this._hass.connection.subscribeMessage(
        (state) => {
          this._applyState(state);
          this._update();
        },
        { type: `${DOMAIN}/subscribe`, entry_id: entryId }
      );
      // The card may have been removed or reconfigured meanwhile.
      if (!this.isConnected || this._config.entry_id !== entryId || this._unsub) unsub();
      else this._unsub = unsub;
    } catch (err) { /* stays usable without live updates */ }
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _applyState(state) {
    this._learned = new Set(state.learned || []);
    const wasLearning = this._learning;
    this._learning = state.learning || null;
    this._learnTimeout = state.learn_timeout || 30;
    if (this._learning && this._learning !== wasLearning) {
      this._deadline = Date.now() + this._learnTimeout * 1000;
      this._startTimer();
    } else if (!this._learning) {
      this._stopTimer();
    }
  }

  _startTimer() {
    this._stopTimer();
    this._timer = setInterval(() => this._updateStatus(), 500);
  }

  _stopTimer() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  // ------------------------------------------------------------- actions

  _errorText(err, buttonId) {
    const name = this._name(buttonId);
    switch (err && err.code) {
      case "learn_timeout": return this._t("timeout", { name });
      case "busy": return this._t("busy");
      case "not_learned": return this._t("not_learned", { name });
      default: return this._t("failed", { msg: (err && err.message) || String(err) });
    }
  }

  _setStatus(text, kind = "") {
    this._status = text ? { text, kind } : null;
    this._update();
  }

  _onButton(buttonId, element) {
    if (!this._remote || !this._remote.buttons.some((b) => b.id === buttonId)) return;
    if (this._learnMode) {
      if (this._learning) return;
      if (this._learned.has(buttonId)) {
        // Do not overwrite an existing code by accident: offer the choice.
        this._selected = buttonId;
        this._setStatus(null);
      } else {
        this._learn(buttonId);
      }
    } else {
      this._send(buttonId, element);
    }
  }

  async _send(buttonId, element) {
    if (!this._learned.has(buttonId)) {
      this._setStatus(this._t("not_learned", { name: this._name(buttonId) }));
      return;
    }
    if (element) {
      element.classList.add("pressed");
      setTimeout(() => element.classList.remove("pressed"), 200);
    }
    try {
      await this._hass.callWS({ type: `${DOMAIN}/send`, entry_id: this._config.entry_id, button: buttonId });
      if (this._learnMode) this._setStatus(this._t("sent", { name: this._name(buttonId) }), "success");
      else if (this._status) this._setStatus(null);
    } catch (err) {
      this._setStatus(this._errorText(err, buttonId), "error");
    }
  }

  async _learn(buttonId) {
    this._selected = null;
    this._status = null;
    // Show the prompt right away; the subscription confirms it shortly after.
    this._applyState({ learned: [...this._learned], learning: buttonId, learn_timeout: this._learnTimeout });
    this._update();
    try {
      const state = await this._hass.callWS({ type: `${DOMAIN}/learn`, entry_id: this._config.entry_id, button: buttonId });
      this._applyState(state);
      this._setStatus(this._t("learned", { name: this._name(buttonId) }), "success");
    } catch (err) {
      if (this._learning === buttonId) this._applyState({ learned: [...this._learned], learn_timeout: this._learnTimeout });
      this._setStatus(this._errorText(err, buttonId), "error");
    }
  }

  async _forget(buttonId) {
    this._selected = null;
    try {
      const state = await this._hass.callWS({ type: `${DOMAIN}/forget`, entry_id: this._config.entry_id, button: buttonId });
      this._applyState(state);
      this._setStatus(this._t("forgotten", { name: this._name(buttonId) }));
    } catch (err) {
      this._setStatus(this._errorText(err, buttonId), "error");
    }
  }

  _toggleLearnMode() {
    if (this._learning) return;
    this._learnMode = !this._learnMode;
    this._selected = null;
    this._status = null;
    this._update();
  }

  // ----------------------------------------------------------- rendering

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style><ha-card></ha-card>`;
    const card = root.querySelector("ha-card");

    if (!this._config.entry_id || this._error || !this._remote) {
      const message = this._config.entry_id
        ? this._error
        : this._t(this.constructor.slug ? "not_found" : "pick_remote");
      if (message) {
        const div = document.createElement("div");
        div.className = "message";
        div.textContent = message;
        card.appendChild(div);
      }
      return;
    }

    card.innerHTML = `
      <div class="header">
        <div class="title"></div>
        <button class="mode" type="button"></button>
      </div>
      <div class="remote"></div>
      <div class="status" role="status" aria-live="polite"></div>`;
    card.querySelector(".title").textContent = this._config.title || this._remote.title;

    const mode = card.querySelector(".mode");
    mode.addEventListener("click", () => this._toggleLearnMode());
    const canLearn = this._config.allow_learning !== false && this._hass?.user?.is_admin !== false;
    if (!canLearn) mode.remove();

    const holder = card.querySelector(".remote");
    holder.innerHTML = this._remote.svg;
    const svg = holder.querySelector("svg");
    if (svg) {
      // The height is capped, not the width: remotes of the same length are
      // then drawn equally long and at the same scale.
      svg.style.maxHeight = `${Number(this._config.max_height) || 650}px`;
      if (Number(this._config.max_width)) svg.style.maxWidth = `${Number(this._config.max_width)}px`;
      svg.querySelectorAll("script").forEach((el) => el.remove());
      svg.querySelectorAll("[data-button]").forEach((el) => {
        el.setAttribute("role", "button");
        el.setAttribute("tabindex", "0");
        el.setAttribute("aria-label", this._name(el.dataset.button));
      });
    }
    const press = (ev) => {
      const el = ev.target.closest && ev.target.closest("[data-button]");
      if (!el || !holder.contains(el)) return;
      if (ev.type === "keydown") {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault();
      }
      this._onButton(el.dataset.button, el);
    };
    holder.addEventListener("click", press);
    holder.addEventListener("keydown", press);

    this._update();
  }

  /** Refresh classes, mode button and status without rebuilding the SVG. */
  _update() {
    const card = this.shadowRoot.querySelector("ha-card");
    const holder = card && card.querySelector(".remote");
    if (!holder || !this._remote) return;

    holder.className = `remote ${this._learnMode ? "learn" : "use"}${this._learning ? " busy" : ""}`;
    holder.querySelectorAll("[data-button]").forEach((el) => {
      const id = el.dataset.button;
      const learned = this._learned.has(id);
      el.classList.toggle("learned", learned);
      el.classList.toggle("unlearned", !learned);
      el.classList.toggle("learning", this._learning === id);
      el.classList.toggle("selected", this._learnMode && this._selected === id && !this._learning);
    });

    const mode = card.querySelector(".mode");
    if (mode) {
      mode.classList.toggle("active", this._learnMode);
      mode.disabled = Boolean(this._learning);
      mode.innerHTML = `<ha-icon icon="${this._learnMode ? "mdi:check" : "mdi:school-outline"}"></ha-icon><span></span>`;
      mode.querySelector("span").textContent = this._t(this._learnMode ? "done" : "learn_mode");
    }
    this._updateStatus();
  }

  _updateStatus() {
    const status = this.shadowRoot.querySelector(".status");
    if (!status) return;
    status.className = "status";
    status.textContent = "";

    if (this._learning) {
      const seconds = Math.max(0, Math.ceil((this._deadline - Date.now()) / 1000));
      status.textContent = this._t("learning", { name: this._name(this._learning), s: seconds });
      return;
    }
    if (this._learnMode && this._selected) {
      const id = this._selected;
      status.textContent = this._t("selected", { name: this._name(id) });
      const actions = document.createElement("div");
      actions.className = "actions";
      const add = (label, cls, handler) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = cls;
        button.textContent = this._t(label);
        button.addEventListener("click", handler);
        actions.appendChild(button);
      };
      add("relearn", "primary", () => this._learn(id));
      add("test", "", () => this._send(id));
      add("forget", "danger", () => this._forget(id));
      status.appendChild(actions);
      return;
    }
    if (this._status) {
      status.textContent = this._status.text;
      if (this._status.kind) status.classList.add(this._status.kind);
      return;
    }
    if (this._learnMode) {
      const total = this._remote.buttons.length;
      const n = this._remote.buttons.filter((b) => this._learned.has(b.id)).length;
      status.textContent = `${this._t("hint_learn")} ${this._t("progress", { n, total })}`;
    }
  }
}

/** Register the card type custom:ir-remote-card-<slug> for one remote. */
function registerRemote(remote) {
  const slug = String(remote.card || "").toLowerCase();
  if (!/^[a-z0-9][a-z0-9._-]*$/.test(slug)) return;
  const known = REMOTES.get(slug);
  REMOTES.set(slug, { entry_id: remote.entry_id, title: remote.title });
  const type = CARD_PREFIX + slug;
  if (!customElements.get(type)) {
    customElements.define(
      type,
      class extends IrRemoteCard {
        static get slug() {
          return slug;
        }
      }
    );
    window.customCards.push({
      type,
      name: remote.title,
      description: "IR Remote",
      preview: true,
      documentationURL: "https://github.com/acidcoke/ha-ir-remote-http-bridge",
    });
  } else {
    const card = window.customCards.find((c) => c.type === type);
    if (card) card.name = remote.title;
  }
  if (!known || known.entry_id !== remote.entry_id) {
    // Cards created from the cache (or before the remote existed) catch up.
    for (const card of INSTANCES) {
      if (card.constructor.slug === slug && card._rawConfig) card.setConfig(card._rawConfig);
    }
  }
}

async function registerRemotes() {
  // The list of the last visit lets the cards render without waiting.
  try {
    JSON.parse(localStorage.getItem(CACHE_KEY) || "[]").forEach(registerRemote);
  } catch (err) { /* no or broken cache */ }

  let hass;
  for (let i = 0; i < 300 && !hass; i++) {
    const main = document.querySelector("home-assistant");
    if (main && main.hass && main.hass.connection) hass = main.hass;
    else await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!hass) return;
  try {
    const remotes = await hass.callWS({ type: `${DOMAIN}/remotes` });
    remotes.forEach(registerRemote);
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(remotes));
    } catch (err) { /* storage unavailable */ }
  } catch (err) { /* integration not loaded */ }
}

if (!customElements.get("ir-remote-card")) {
  customElements.define("ir-remote-card", IrRemoteCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ir-remote-card",
    name: "IR Remote Card",
    description: "Remote control with learn mode - pick the remote in the card settings",
    preview: false,
    documentationURL: "https://github.com/acidcoke/ha-ir-remote-http-bridge",
  });
  registerRemotes();
}
