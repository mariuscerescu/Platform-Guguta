/* Guguță Companion — dependency-free sprite widget. See README for host integration. */
(function () {
  'use strict';

  if (customElements.get('guguta-companion')) return;

  const CELL_WIDTH = 192;
  const CELL_HEIGHT = 208;
  const ATLAS_WIDTH = 1536;
  const ATLAS_HEIGHT = 2288;
  const ANIMATIONS = Object.freeze({
    idle: { row: 0, durations: [280, 110, 110, 140, 140, 320] },
    'running-right': { row: 1, durations: [120, 120, 120, 120, 120, 120, 120, 220] },
    'running-left': { row: 2, durations: [120, 120, 120, 120, 120, 120, 120, 220] },
    waving: { row: 3, durations: [140, 140, 140, 280] },
    jumping: { row: 4, durations: [140, 140, 140, 140, 280] },
    failed: { row: 5, durations: [140, 140, 140, 140, 140, 140, 140, 240] },
    waiting: { row: 6, durations: [150, 150, 150, 150, 150, 260] },
    running: { row: 7, durations: [120, 120, 120, 120, 120, 220] },
    review: { row: 8, durations: [150, 150, 150, 150, 150, 280] },
    // Reuse calm poses without changing the original activity and quiz animations.
    // Every voice sequence starts neutral, including the reduced-motion frame.
    'voice-speaking': {
      frames: [[0, 0], [0, 2], [0, 3], [0, 0], [6, 0], [6, 1], [6, 0], [0, 0], [7, 4], [0, 0]],
      durations: [1200, 100, 110, 900, 700, 750, 650, 1700, 900, 1800]
    },
    'voice-listening': {
      frames: [[0, 0], [0, 1], [0, 2], [0, 3], [0, 0]],
      durations: [3300, 110, 110, 140, 2400]
    },
    'voice-thinking': {
      frames: [[0, 0], [7, 0], [7, 2], [7, 3]],
      durations: [800, 1000, 900, 1100]
    }
  });
  const DEFAULT_STATUS = Object.freeze({
    idle: 'Gata să te ajut',
    'running-right': 'Pe drum',
    'running-left': 'Pe drum',
    waving: 'Bună!',
    jumping: 'Bravo!',
    failed: 'Hai să mai încercăm',
    waiting: 'Aștept următorul pas',
    running: 'Mă ocup',
    review: 'Verific răspunsul',
    'voice-speaking': 'Îți răspund…',
    'voice-listening': 'Te ascult…',
    'voice-thinking': 'Mă gândesc…'
  });
  const CONTEXT_KEYS = Object.freeze([
    'source', 'subjectId', 'subjectLabel', 'grade', 'notebookId',
    'quizId', 'lessonId', 'lessonTitle', 'locale'
  ]);

  class GugutaCompanion extends HTMLElement {
    static get observedAttributes() {
      return ['src', 'name', 'activity', 'status', 'state', 'collapsed', 'follow-pointer', 'reduced-motion'];
    }

    constructor() {
      super();
      this._root = this.attachShadow({ mode: 'open' });
      // All markup is constant. Attribute values are assigned only with textContent / setAttribute.
      this._root.innerHTML = `
        <style>
          :host {
            --guguta-panel: #25262a;
            --guguta-panel-hover: #36383e;
            --guguta-text: #fbfbfc;
            --guguta-muted: #babcc4;
            --guguta-focus: #a4ccff;
            display: block;
            width: min(100%, var(--guguta-width, 320px));
            max-width: 340px;
            color: var(--guguta-text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 14px;
            line-height: 1.4;
            isolation: isolate;
          }
          *, *::before, *::after { box-sizing: border-box; }
          [hidden] { display: none !important; }
          button { font: inherit; color: inherit; cursor: pointer; -webkit-tap-highlight-color: transparent; }
          button:focus-visible { outline: 3px solid var(--guguta-focus); outline-offset: 4px; }
          .frame { display: flex; flex-direction: column; align-items: center; width: 100%; }
          .bubble {
            position: relative;
            width: 100%;
            padding: 15px 18px 14px;
            border: 1px solid rgba(255, 255, 255, .08);
            border-radius: 19px;
            background: var(--guguta-panel);
            box-shadow: 0 8px 24px rgba(0, 0, 0, .13);
            text-align: left;
            overflow-wrap: anywhere;
          }
          .bubble::after {
            content: '';
            position: absolute;
            left: calc(50% - 6px);
            bottom: -6px;
            width: 12px;
            height: 12px;
            background: var(--guguta-panel);
            border-radius: 0 0 3px 0;
            transform: rotate(45deg);
          }
          .context { margin-bottom: 4px; color: var(--guguta-muted); font-size: 11px; font-weight: 500; }
          .activity { display: block; font-size: 15px; font-weight: 650; letter-spacing: -.015em; }
          .status { margin-top: 3px; color: var(--guguta-muted); font-size: 12px; line-height: 1.5; }
          .stage {
            position: relative;
            width: min(100%, var(--guguta-mascot-size, 260px));
            aspect-ratio: 12 / 13;
            margin: 9px auto 1px;
          }
          canvas { display: block; width: 100%; height: 100%; object-fit: contain; }
          .fallback {
            position: absolute;
            inset: 0;
            display: grid;
            place-content: center;
            gap: 8px;
            padding: 24px;
            color: #707782;
            text-align: center;
            font-size: 13px;
          }
          .fallback-symbol { font-size: 30px; color: #9299a6; line-height: 1; }
          .toolbar-region { position: relative; width: 100%; }
          .toolbar {
            display: flex;
            align-items: center;
            justify-content: center;
            width: min(168px, 100%);
            min-height: 54px;
            margin: 0 auto;
            padding: 4px 5px;
            border: 1px solid rgba(255, 255, 255, .08);
            border-radius: 999px;
            background: var(--guguta-panel);
            box-shadow: 0 7px 18px rgba(0, 0, 0, .15);
          }
          .tool {
            flex: 1 1 0;
            display: grid;
            place-items: center;
            min-width: 0;
            min-height: 44px;
            padding: 8px;
            border: 0;
            border-radius: 999px;
            background: transparent;
            transition: background .15s ease;
          }
          .tool:hover, .voice[aria-pressed="true"] { background: var(--guguta-panel-hover); }
          .tool svg { display: block; width: 21px; height: 21px; pointer-events: none; }
          .separator { flex: 0 0 1px; height: 19px; background: rgba(255, 255, 255, .13); margin: 0 1px; }
          .restore {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            max-width: 100%;
            min-height: 44px;
            margin-inline: auto;
            padding: 11px 17px;
            border: 1px solid rgba(255, 255, 255, .12);
            border-radius: 999px;
            background: var(--guguta-panel);
            box-shadow: 0 7px 18px rgba(0, 0, 0, .13);
          }
          .restore:hover { background: var(--guguta-panel-hover); }
          .restore svg { width: 17px; height: 17px; flex: 0 0 auto; }
          .restore span { overflow-wrap: anywhere; }
          @media (prefers-reduced-motion: reduce) { .tool { transition: none; } }
          :host([reduced-motion]) .tool { transition: none; }
          @media (forced-colors: active) {
            .bubble, .toolbar, .restore { border: 1px solid ButtonText; }
            .separator { background: ButtonText; }
          }
        </style>
        <div class="frame" part="frame">
          <div class="bubble" part="bubble" role="status" aria-live="polite" aria-atomic="true">
            <div class="context" part="context" hidden></div>
            <strong class="activity" part="activity"></strong>
            <div class="status" part="status"></div>
          </div>
          <div class="stage" part="stage">
            <canvas width="192" height="208" role="img" part="mascot"></canvas>
            <div class="fallback" role="status">
              <span class="fallback-symbol" aria-hidden="true">◌</span>
              <span class="fallback-text">Se încarcă mascota…</span>
            </div>
          </div>
          <div class="toolbar-region">
            <div class="toolbar" part="toolbar" role="group" aria-label="Comenzi pentru mascotă">
              <button type="button" class="tool compose" part="compose-button" aria-label="Scrie un mesaj" title="Scrie un mesaj">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7"/><path d="m16 3 5 5M10 14l-1 4 4-1L22 8a1.4 1.4 0 0 0 0-2l-3-3a1.4 1.4 0 0 0-2 0Z"/></svg>
              </button>
              <span class="separator" aria-hidden="true"></span>
              <button type="button" class="tool voice" part="voice-button" aria-label="Începe conversația vocală" aria-pressed="false" title="Începe conversația vocală">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4"/></svg>
              </button>
              <span class="separator" aria-hidden="true"></span>
              <button type="button" class="tool collapse" part="collapse-button" aria-expanded="true" aria-label="Restrânge mascota" title="Restrânge mascota">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 14 6-6 6 6"/></svg>
              </button>
            </div>
          </div>
        </div>
        <button type="button" class="restore" part="restore-button" aria-expanded="false" hidden>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
          <span></span>
        </button>`;

      this._canvas = this._root.querySelector('canvas');
      this._context = this._canvas.getContext('2d');
      this._frame = this._root.querySelector('.frame');
      this._contextText = this._root.querySelector('.context');
      this._activityText = this._root.querySelector('.activity');
      this._statusText = this._root.querySelector('.status');
      this._fallback = this._root.querySelector('.fallback');
      this._fallbackText = this._root.querySelector('.fallback-text');
      this._restore = this._root.querySelector('.restore');
      this._voiceButton = this._root.querySelector('.voice');
      this._collapseButton = this._root.querySelector('.collapse');
      this._connected = false;
      this._educationalContext = Object.freeze({});
      this._intersecting = true;
      this._image = null;
      this._loadingImage = null;
      this._loadToken = 0;
      this._loadedSrc = '';
      this._raf = 0;
      this._frameIndex = 0;
      this._elapsed = 0;
      this._lastTime = 0;
      this._lookDirection = null;
      this._pointerListening = false;
      this._motionQuery = null;
      this._tick = this._tick.bind(this);
      this._onVisibility = this._onVisibility.bind(this);
      this._onMotionChange = this._onMotionChange.bind(this);
      this._onPointerMove = this._onPointerMove.bind(this);
      this._onPointerLeave = this._onPointerLeave.bind(this);

      this._root.querySelector('.compose').addEventListener('click', (event) => {
        event.stopPropagation();
        this._emit('guguta-compose');
      });
      this._voiceButton.addEventListener('click', (event) => {
        event.stopPropagation();
        this._emit('guguta-voice', { mode: 'conversation' });
      });
      this._collapseButton.addEventListener('click', (event) => {
        event.stopPropagation();
        this.collapsed = true;
        this._restore.focus();
        this._emit('guguta-collapse');
      });
      this._restore.addEventListener('click', (event) => {
        event.stopPropagation();
        this.collapsed = false;
        this._collapseButton.focus();
        this._emit('guguta-collapse');
      });
    }

    connectedCallback() {
      this._connected = true;
      this._intersecting = true;
      this._motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      if (this._motionQuery.addEventListener) this._motionQuery.addEventListener('change', this._onMotionChange);
      else this._motionQuery.addListener(this._onMotionChange);
      document.addEventListener('visibilitychange', this._onVisibility);
      if ('IntersectionObserver' in window) {
        this._observer = new IntersectionObserver((entries) => {
          if (!this._connected) return;
          this._intersecting = entries.some((entry) => entry.isIntersecting);
          this._syncRunning();
        });
        this._observer.observe(this);
      }
      this._updateText();
      this._updateCollapsed();
      this._updatePointerListener();
      this._loadSprite();
    }

    disconnectedCallback() {
      this._connected = false;
      this._lookDirection = null;
      this._stopAnimation();
      this._removePointerListener();
      document.removeEventListener('visibilitychange', this._onVisibility);
      if (this._motionQuery) {
        if (this._motionQuery.removeEventListener) this._motionQuery.removeEventListener('change', this._onMotionChange);
        else this._motionQuery.removeListener(this._onMotionChange);
      }
      this._motionQuery = null;
      if (this._observer) this._observer.disconnect();
      this._observer = null;
      this._loadToken += 1;
      if (this._loadingImage) {
        this._loadingImage.onload = null;
        this._loadingImage.onerror = null;
        this._loadingImage = null;
      }
    }

    attributeChangedCallback(attribute, oldValue, newValue) {
      if (oldValue === newValue) return;
      if (attribute === 'src') {
        if (this._connected) this._loadSprite();
        return;
      }
      if (attribute === 'state') {
        this._frameIndex = 0;
        this._elapsed = 0;
        this._lastTime = 0;
        this._lookDirection = null;
      }
      if (attribute === 'collapsed') this._updateCollapsed();
      if (attribute === 'follow-pointer') this._updatePointerListener();
      if (attribute === 'reduced-motion') this._onMotionChange();
      this._updateText();
      this._renderFrame();
      this._syncRunning();
    }

    get name() { return this.getAttribute('name') || 'Guguță'; }
    set name(value) { this.setAttribute('name', String(value)); }
    get src() { return this.getAttribute('src') || ''; }
    set src(value) { this.setAttribute('src', String(value)); }
    get activity() { return this.getAttribute('activity') ?? 'Învățăm împreună'; }
    set activity(value) { this.setAttribute('activity', String(value)); }
    get status() { return this.getAttribute('status') ?? DEFAULT_STATUS[this.state]; }
    set status(value) { this.setAttribute('status', String(value)); }
    get state() {
      const state = this.getAttribute('state');
      return Object.prototype.hasOwnProperty.call(ANIMATIONS, state) ? state : 'idle';
    }
    set state(value) { this.setState(value); }
    get collapsed() { return this.hasAttribute('collapsed'); }
    set collapsed(value) { this.toggleAttribute('collapsed', Boolean(value)); }
    get followPointer() { return this.hasAttribute('follow-pointer'); }
    set followPointer(value) { this.toggleAttribute('follow-pointer', Boolean(value)); }
    get reducedMotion() { return this.hasAttribute('reduced-motion'); }
    set reducedMotion(value) { this.toggleAttribute('reduced-motion', Boolean(value)); }
    get context() { return Object.assign({}, this._educationalContext); }
    set context(value) { this.setContext(value); }

    setContext(context) {
      if (context !== null && (typeof context !== 'object' || Array.isArray(context))) {
        throw new TypeError('setContext expects an object or null.');
      }
      const snapshot = {};
      if (context) {
        for (const key of CONTEXT_KEYS) {
          if (!Object.prototype.hasOwnProperty.call(context, key)) continue;
          const value = context[key];
          if (typeof value === 'string' || (key === 'grade' && typeof value === 'number' && Number.isFinite(value))) {
            snapshot[key] = value;
          }
        }
      }
      // Replace the complete context; omitted fields never survive a lesson/class change.
      this._educationalContext = Object.freeze(snapshot);
      this._updateText();
      this.dispatchEvent(new CustomEvent('guguta-contextchange', {
        bubbles: true,
        composed: true,
        detail: Object.freeze({ name: this.name, context: Object.freeze(this.context) })
      }));
      return this;
    }

    setStatus(update) {
      if (!update || typeof update !== 'object' || Array.isArray(update)) {
        throw new TypeError('setStatus expects an object with activity, status, and/or state.');
      }
      // Validate before applying any changes so an invalid state cannot leave a partial update.
      if ('state' in update && !Object.prototype.hasOwnProperty.call(ANIMATIONS, update.state)) {
        throw new RangeError('Unknown Guguță animation: ' + String(update.state));
      }
      if ('activity' in update) this.activity = update.activity;
      if ('status' in update) this.status = update.status;
      if ('state' in update) this.setState(update.state);
      return this;
    }

    setState(animationName) {
      if (!Object.prototype.hasOwnProperty.call(ANIMATIONS, animationName)) {
        throw new RangeError('Unknown Guguță animation: ' + String(animationName));
      }
      this.setAttribute('state', animationName);
      return this;
    }

    _updateText() {
      const context = this._educationalContext;
      const subject = (context.subjectLabel || '').trim();
      const grade = context.grade === undefined ? '' : String(context.grade).trim();
      const contextLabel = [subject, grade ? (subject ? 'clasa ' : 'Clasa ') + grade : ''].filter(Boolean).join(' · ');
      this._contextText.textContent = contextLabel;
      this._contextText.hidden = !contextLabel;
      this._activityText.textContent = this.activity;
      this._statusText.textContent = this.status;
      this._canvas.setAttribute('aria-label', 'Mascota ' + this.name);
      this._restore.querySelector('span').textContent = 'Arată ' + this.name;
      this._restore.setAttribute('aria-label', 'Arată ' + this.name);
      this._collapseButton.setAttribute('aria-label', 'Restrânge ' + this.name);
      this._root.querySelector('.toolbar').setAttribute('aria-label', 'Comenzi pentru ' + this.name);
    }

    _updateCollapsed() {
      this._frame.hidden = this.collapsed;
      this._restore.hidden = !this.collapsed;
      this._collapseButton.setAttribute('aria-expanded', String(!this.collapsed));
      this._restore.setAttribute('aria-expanded', String(!this.collapsed));
      if (this.collapsed) {
        this._lookDirection = null;
      }
      this._syncRunning();
    }

    _emit(type, extra) {
      this.dispatchEvent(new CustomEvent(type, {
        bubbles: true,
        composed: true,
        detail: Object.freeze(Object.assign({
          name: this.name,
          collapsed: this.collapsed,
          context: Object.freeze(this.context)
        }, extra || {}))
      }));
    }

    _loadSprite() {
      const source = this.src;
      const token = ++this._loadToken;
      if (this._loadingImage) {
        this._loadingImage.onload = null;
        this._loadingImage.onerror = null;
        this._loadingImage = null;
      }
      this._stopAnimation();
      if (this._image && this._loadedSrc === source) {
        this._fallback.hidden = true;
        this._canvas.hidden = false;
        this._renderFrame();
        this._syncRunning();
        return;
      }
      this._image = null;
      this._loadedSrc = '';
      this._canvas.hidden = true;
      this._fallback.hidden = false;
      this._fallbackText.textContent = source ? 'Se încarcă mascota…' : 'Imaginea mascotei nu este configurată.';
      if (!source) return;
      if (!this._context) {
        this._fallbackText.textContent = 'Acest browser nu poate afișa mascota animată.';
        return;
      }
      const sprite = new Image();
      this._loadingImage = sprite;
      sprite.decoding = 'async';
      sprite.onload = () => {
        if (!this._connected || token !== this._loadToken) return;
        this._loadingImage = null;
        sprite.onload = null;
        sprite.onerror = null;
        if (sprite.naturalWidth !== ATLAS_WIDTH || sprite.naturalHeight !== ATLAS_HEIGHT) {
          this._fallbackText.textContent = 'Format de mascotă incompatibil. Imaginea trebuie să aibă 1536 × 2288 px.';
          return;
        }
        this._image = sprite;
        this._loadedSrc = source;
        this._frameIndex = 0;
        this._elapsed = 0;
        this._fallback.hidden = true;
        this._canvas.hidden = false;
        this._renderFrame();
        this._syncRunning();
      };
      sprite.onerror = () => {
        if (!this._connected || token !== this._loadToken) return;
        this._loadingImage = null;
        sprite.onload = null;
        sprite.onerror = null;
        this._fallbackText.textContent = 'Mascota nu s-a putut încărca. Comenzile rămân disponibile.';
      };
      sprite.src = source;
    }

    _prefersReducedMotion() {
      return this.reducedMotion || Boolean(this._motionQuery && this._motionQuery.matches);
    }

    _shouldAnimate() {
      return this._connected && Boolean(this._image) && !this.collapsed &&
        !document.hidden && this._intersecting && !this._prefersReducedMotion() && this._lookDirection === null;
    }

    _syncRunning() {
      if (!this._shouldAnimate()) {
        this._stopAnimation();
        return;
      }
      if (!this._raf) {
        this._lastTime = 0;
        this._raf = requestAnimationFrame(this._tick);
      }
    }

    _stopAnimation() {
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = 0;
      this._lastTime = 0;
    }

    _tick(now) {
      this._raf = 0;
      if (!this._shouldAnimate()) return;
      const animation = ANIMATIONS[this.state];
      if (this._lastTime) this._elapsed += Math.min(now - this._lastTime, 250);
      this._lastTime = now;
      let changed = false;
      while (this._elapsed >= animation.durations[this._frameIndex]) {
        this._elapsed -= animation.durations[this._frameIndex];
        this._frameIndex = (this._frameIndex + 1) % animation.durations.length;
        changed = true;
      }
      if (changed) this._renderFrame();
      this._raf = requestAnimationFrame(this._tick);
    }

    _renderFrame() {
      if (!this._context || !this._image) return;
      const reduced = this._prefersReducedMotion();
      const animation = ANIMATIONS[this.state];
      const frameIndex = reduced ? 0 : this._frameIndex;
      let row = animation.frames ? animation.frames[frameIndex][0] : animation.row;
      let column = animation.frames ? animation.frames[frameIndex][1] : frameIndex;
      if (this._lookDirection !== null && !reduced && (this.state === 'idle' || this.state === 'waiting')) {
        row = this._lookDirection < 8 ? 9 : 10;
        column = this._lookDirection % 8;
      }
      this._context.clearRect(0, 0, CELL_WIDTH, CELL_HEIGHT);
      this._context.drawImage(this._image, column * CELL_WIDTH, row * CELL_HEIGHT,
        CELL_WIDTH, CELL_HEIGHT, 0, 0, CELL_WIDTH, CELL_HEIGHT);
    }

    _onVisibility() {
      if (document.hidden) {
        this._lookDirection = null;
      }
      this._renderFrame();
      this._syncRunning();
    }

    _onMotionChange() {
      this._lookDirection = null;
      this._frameIndex = 0;
      this._elapsed = 0;
      this._renderFrame();
      this._syncRunning();
    }

    _updatePointerListener() {
      if (this._connected && this.followPointer) {
        if (!this._pointerListening) {
          document.addEventListener('pointermove', this._onPointerMove, { passive: true });
          document.addEventListener('pointerleave', this._onPointerLeave, { passive: true });
          this._pointerListening = true;
        }
      } else {
        this._removePointerListener();
        this._lookDirection = null;
        this._renderFrame();
        this._syncRunning();
      }
    }

    _removePointerListener() {
      document.removeEventListener('pointermove', this._onPointerMove);
      document.removeEventListener('pointerleave', this._onPointerLeave);
      this._pointerListening = false;
    }

    _onPointerMove(event) {
      if (!this._connected || this.collapsed || !this._intersecting || document.hidden ||
        this._prefersReducedMotion() || event.pointerType === 'touch' ||
        (this.state !== 'idle' && this.state !== 'waiting')) return;
      const bounds = this._canvas.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const dx = event.clientX - (bounds.left + bounds.width * 0.5);
      const dy = event.clientY - (bounds.top + bounds.height * 0.36);
      const deadZone = Math.max(20, bounds.width * 0.1);
      let direction = null;
      if (Math.hypot(dx, dy) >= deadZone) {
        // v2 look rows proceed clockwise: 0 up, 4 right, 8 down, 12 left.
        const angle = (Math.atan2(dx, -dy) + Math.PI * 2) % (Math.PI * 2);
        direction = Math.round(angle / (Math.PI * 2) * 16) % 16;
      }
      if (direction === this._lookDirection) return;
      this._lookDirection = direction;
      this._renderFrame();
      this._syncRunning();
    }

    _onPointerLeave() {
      if (this._lookDirection === null) return;
      this._lookDirection = null;
      this._renderFrame();
      this._syncRunning();
    }
  }

  customElements.define('guguta-companion', GugutaCompanion);
})();
