(function () {
  "use strict";

  const DETECTORS = ["D1", "D2", "D3", "D4", "D5", "D6"];
  const ALLOWED_FITS_ORIGINS = new Set([
    "https://irsa.ipac.caltech.edu",
    "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com",
  ]);

  function isSafeRemoteUrl(rawUrl) {
    if (typeof rawUrl !== "string" || !rawUrl || /[\s\x00-\x1f\x7f\\#?]/.test(rawUrl) || rawUrl.includes("..")) return false;
    try {
      const u = new URL(rawUrl);
      if (!ALLOWED_FITS_ORIGINS.has(u.origin) || u.username || u.password || u.port !== "" || u.search !== "" || u.hash !== "") {
        return false;
      }
      if (rawUrl.slice(u.origin.length) !== u.pathname) return false;
      const relPath = u.pathname.slice(1);
      if (!/^[A-Za-z0-9][A-Za-z0-9_./-]{0,511}$/.test(relPath) || relPath.includes("//")) {
        return false;
      }
      if (u.hostname === "irsa.ipac.caltech.edu") {
        return relPath.startsWith("ibe/data/spherex/") || relPath.startsWith("data/") || /\.(fits|fits\.fz|fz)$/i.test(relPath);
      }
      return true;
    } catch (_e) {
      return false;
    }
  }

  const state = {
    coord: "WISE 0855",
    fovArcmin: 6.5,
    epochYr: 2026.0,
    detector: "D6",
    mode: "play",
    stretch: "asinh",
    visitIdx: 0,
    playing: true,
    live: false,
    showGaia: true,
    showMask: true,
    embed: false,
    payload: null,
    timerId: null,
    querySeq: 0,
    abortController: null,
  };

  const els = {
    form: document.getElementById("sky-query-form"),
    coordInput: document.getElementById("coord-input"),
    fovSelect: document.getElementById("fov-select"),
    epochInput: document.getElementById("epoch-input"),
    liveToggle: document.getElementById("live-toggle"),
    modeBadge: document.getElementById("mode-badge"),
    statusBanner: document.getElementById("status-banner"),
    skyCanvas: document.getElementById("sky-canvas"),
    spectrumCanvas: document.getElementById("spectrum-canvas"),
    matrixCanvas: document.getElementById("matrix-canvas"),
    playToggle: document.getElementById("play-toggle"),
    scrubber: document.getElementById("visit-scrubber"),
    visitLabel: document.getElementById("visit-label"),
    stretchSelect: document.getElementById("stretch-select"),
    gaiaToggle: document.getElementById("gaia-overlay-toggle"),
    maskToggle: document.getElementById("mask-overlay-toggle"),
    pixelReadout: document.getElementById("pixel-readout"),
    moleculeList: document.getElementById("molecule-list"),
    framesTbody: document.getElementById("frames-tbody"),
    framesHeading: document.getElementById("frames-heading"),
    spectrumHeading: document.getElementById("spectrum-heading"),
    copyUrlBtn: document.getElementById("copy-url-btn"),
  };

  function setStatus(text, isError) {
    els.statusBanner.textContent = text;
    els.statusBanner.classList.toggle("error", Boolean(isError));
  }

  function shortestRaDeltaDeg(raDeg, refRaDeg) {
    return ((((raDeg - refRaDeg) % 360.0) + 540.0) % 360.0) - 180.0;
  }

  function propagatePositionDeg(raDeg, decDeg, pmraMasYr, pmdecMasYr, dtYr) {
    const cosd = Math.max(Math.cos((decDeg * Math.PI) / 180.0), 1e-6);
    const raOut = (((raDeg + (pmraMasYr * dtYr) / (3600000.0 * cosd)) % 360.0) + 360.0) % 360.0;
    const decOut = Math.max(-90.0, Math.min(90.0, decDeg + (pmdecMasYr * dtYr) / 3600000.0));
    return [raOut, decOut];
  }

  function angularSepArcmin(ra1, dec1, ra2, dec2) {
    const toRad = Math.PI / 180.0;
    const d1 = dec1 * toRad;
    const d2 = dec2 * toRad;
    const dr = (ra2 - ra1) * toRad;
    const dd = d2 - d1;
    const a = Math.sin(dd / 2) ** 2 + Math.cos(d1) * Math.cos(d2) * (Math.sin(dr / 2) ** 2);
    return (2.0 * Math.asin(Math.min(1.0, Math.sqrt(Math.max(0.0, a)))) * 180.0 / Math.PI) * 60.0;
  }

  function isFiniteNumber(v) {
    return typeof v === "number" && Number.isFinite(v);
  }

  function parseStrictNumber(raw) {
    if (typeof raw !== "string") return NaN;
    const trimmed = raw.trim();
    if (!trimmed) return NaN;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : NaN;
  }

  function readGridCell(grid, y, x) {
    return Array.isArray(grid) && Array.isArray(grid[y]) ? grid[y][x] : NaN;
  }

  function hasValidFrames(ts) {
    return Boolean(
      ts && Array.isArray(ts.frames_by_visit) && ts.frames_by_visit.length > 0
      && Array.isArray(ts.frames_by_visit[0]) && ts.frames_by_visit[0].length > 0
      && Array.isArray(ts.frames_by_visit[0][0]) && ts.frames_by_visit[0][0].length > 0
    );
  }

  function parseSexagesimalPair(clean) {
    const hms = clean.match(
      /^(\d+)\s*h\s*(\d+)\s*m\s*(\d+(?:\.\d+)?)\s*s(?:\s*,\s*|\s+)([+-]?\d+)\s*d\s*(\d+)\s*m\s*(\d+(?:\.\d+)?)\s*s$/i
    );
    const colons = clean.match(
      /^(\d+):(\d+):(\d+(?:\.\d+)?)(?:\s*,\s*|\s+)([+-]?\d+):(\d+):(\d+(?:\.\d+)?)$/
    );
    const m = hms || colons;
    if (!m) return null;
    const rh = Number(m[1]);
    const rm = Number(m[2]);
    const rs = Number(m[3]);
    const ddAbs = Math.abs(Number(m[4]));
    const dm = Number(m[5]);
    const ds = Number(m[6]);
    if (
      !Number.isInteger(rh) || !Number.isInteger(rm) || !Number.isFinite(rs)
      || !Number.isInteger(ddAbs) || !Number.isInteger(dm) || !Number.isFinite(ds)
      || rh < 0 || rh > 24 || rm < 0 || rm >= 60 || rs < 0 || rs >= 60
      || ddAbs < 0 || ddAbs > 90 || dm < 0 || dm >= 60 || ds < 0 || ds >= 60
      || (rh === 24 && (rm > 0 || rs > 0))
      || (ddAbs === 90 && (dm > 0 || ds > 0))
    ) {
      return null;
    }
    const ra = (rh + rm / 60.0 + rs / 3600.0) * 15.0;
    const dSign = m[4].startsWith("-") ? -1.0 : 1.0;
    const dec = dSign * (ddAbs + dm / 60.0 + ds / 3600.0);
    if (!Number.isFinite(ra) || ra < 0 || ra > 360 || !Number.isFinite(dec) || dec < -90 || dec > 90) return null;
    return [((ra % 360.0) + 360.0) % 360.0, dec];
  }

  function decodeB64Bytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function decodeStaticDetectorTimeseries(bundle, tgt, detectorId) {
    if (!tgt.manifest || !tgt.pack_b64 || !tgt.mask_b64) return null;
    tgt._detCache = tgt._detCache || {};
    if (tgt._detCache[detectorId]) return tgt._detCache[detectorId];

    const manifest = tgt.manifest;
    const packLayout = manifest.pack_binary_layout;
    const maskLayout = manifest.quality_mask_layout;
    const shape = packLayout.shape || [];
    const [nV, nD, ny, nx] = shape;
    const detIdx = DETECTORS.indexOf(detectorId);
    if (detIdx < 0 || nV < 1 || nV > 16 || detIdx >= nD || ny < 1 || ny > 256 || nx < 1 || nx > 256) return null;

    if (!tgt._rawPack) tgt._rawPack = decodeB64Bytes(tgt.pack_b64);
    if (!tgt._rawMask) tgt._rawMask = decodeB64Bytes(tgt.mask_b64);
    const expectedElems = nV * nD * ny * nx;
    if (tgt._rawPack.length !== expectedElems * 2 || tgt._rawMask.length !== expectedElems) return null;

    const flags = maskLayout.flag_bits || {};
    const irsaBit = Number(flags.IRSA_REJECTED || 1);
    const overBit = Number(flags.OVERFLOW_SATURATED || 2);
    const edgeBit = Number(flags.EDGE_MASKED || 4);
    const badBits = irsaBit | overBit | edgeBit;
    const fluxScale = Number(packLayout.flux_scale);
    const fluxZero = Number(packLayout.flux_zero);
    const invalidU16 = Number(packLayout.invalid_u16);

    const framesByVisit = [];
    const maskOverlay = Array.from({ length: ny }, () => new Array(nx).fill(0));
    let irsaPx = 0;
    let overPx = 0;
    let edgePx = 0;

    for (let v = 0; v < nV; v++) {
      const planeBase = (v * nD + detIdx) * ny * nx;
      const grid = [];
      for (let y = 0; y < ny; y++) {
        const row = new Array(nx);
        const rowBase = planeBase + y * nx;
        for (let x = 0; x < nx; x++) {
          const elemIdx = rowBase + x;
          const bOff = elemIdx * 2;
          const rawVal = tgt._rawPack[bOff] | (tgt._rawPack[bOff + 1] << 8);
          const mVal = tgt._rawMask[elemIdx];
          if ((mVal & irsaBit) !== 0) irsaPx += 1;
          if ((mVal & overBit) !== 0) overPx += 1;
          if ((mVal & edgeBit) !== 0) edgePx += 1;
          maskOverlay[y][x] |= mVal;
          row[x] = rawVal === invalidU16 || (mVal & badBits) !== 0
            ? null
            : Math.round((rawVal * fluxScale + fluxZero) * 1e4) / 1e4;
        }
        grid.push(row);
      }
      framesByVisit.push(grid);
    }

    const stack = Array.from({ length: ny }, (_v, y) =>
      Array.from({ length: nx }, (_x, x) => {
        let sum = 0;
        let cnt = 0;
        for (let v = 0; v < nV; v++) {
          const val = framesByVisit[v][y][x];
          if (val !== null) { sum += val; cnt += 1; }
        }
        return cnt > 0 ? Math.round((sum / cnt) * 1e4) / 1e4 : null;
      })
    );
    const difference = Array.from({ length: ny }, (_v, y) =>
      Array.from({ length: nx }, (_x, x) => {
        const a = framesByVisit[0][y][x];
        const b = framesByVisit[nV - 1][y][x];
        return a === null || b === null ? null : Math.round((b - a) * 1e4) / 1e4;
      })
    );

    const ts = {
      target_id: manifest.target_id,
      detector: detectorId,
      shape: [ny, nx],
      wavelength_range_um: (bundle.detector_wavelength_ranges_um && bundle.detector_wavelength_ranges_um[detectorId]) || [0.75, 5.0],
      visits: manifest.visits,
      frames_by_visit: framesByVisit,
      stack,
      difference,
      mask_overlay: maskOverlay,
      mask_summary: { irsa_rejected_px: irsaPx, overflow_saturated_px: overPx, edge_masked_px: edgePx },
      center_ra_deg: Number(manifest.center_ra_deg),
      center_dec_deg: Number(manifest.center_dec_deg),
      fov_arcmin: Number(manifest.fov_arcmin),
      pixel_scale_arcsec: Number(manifest.pixel_scale_arcsec),
      target_j2000_ra_deg: Number(manifest.target_j2000_ra_deg),
      target_j2000_dec_deg: Number(manifest.target_j2000_dec_deg),
    };
    tgt._detCache[detectorId] = ts;
    return ts;
  }

  function resolveOfflineSkyPayload() {
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
    if (!bundle || !bundle.targets) return null;

    const clean = (state.coord || "").trim();
    const norm = clean.toLowerCase();
    const targetsList = Object.values(bundle.targets);
    const dtYr = state.epochYr - 2000.0;

    let qRa;
    let qDec;
    let explicitId = null;
    for (const tgt of targetsList) {
      if (norm === tgt.name.toLowerCase() || (tgt.aliases || []).includes(norm)) {
        qRa = tgt.ra_deg_j2000;
        qDec = tgt.dec_deg_j2000;
        explicitId = tgt.target_id;
        break;
      }
    }
    if (explicitId === null) {
      const mNum = clean.match(/^([+-]?\d+(?:\.\d+)?)(?:\s*,\s*|\s+)([+-]?\d+(?:\.\d+)?)$/);
      const sexa = mNum ? null : parseSexagesimalPair(clean);
      if (mNum) {
        const raV = Number(mNum[1]);
        const decV = Number(mNum[2]);
        if (!Number.isFinite(raV) || raV < 0 || raV > 360 || !Number.isFinite(decV) || decV < -90 || decV > 90) {
          return { error: "Numeric coordinates out of bounds" };
        }
        qRa = ((raV % 360.0) + 360.0) % 360.0;
        qDec = decV;
      } else if (sexa) {
        [qRa, qDec] = sexa;
      } else {
        return { error: "Invalid sky coordinate or unknown target name (offline fallback)" };
      }
    }

    let matched = null;
    let matchRaEp = qRa;
    let matchDecEp = qDec;
    let bestSep = Infinity;
    for (const tgt of targetsList) {
      const [raEp, decEp] = propagatePositionDeg(tgt.ra_deg_j2000, tgt.dec_deg_j2000, tgt.pm_ra_mas_yr, tgt.pm_dec_mas_yr, dtYr);
      if (explicitId === tgt.target_id) {
        matched = tgt;
        matchRaEp = raEp;
        matchDecEp = decEp;
        bestSep = 0.0;
        break;
      }
      const sep = Math.min(
        angularSepArcmin(qRa, qDec, tgt.ra_deg_j2000, tgt.dec_deg_j2000),
        angularSepArcmin(qRa, qDec, raEp, decEp)
      );
      if (sep <= Math.min(state.fovArcmin / 2.0, 3.25) && sep < bestSep) {
        matched = tgt;
        matchRaEp = raEp;
        matchDecEp = decEp;
        bestSep = sep;
      }
    }

    if (!matched) {
      return {
        data: {
          query: {
            coord_input: state.coord,
            ra_deg: qRa,
            dec_deg: qDec,
            ra_deg_at_epoch: qRa,
            dec_deg_at_epoch: qDec,
            fov_arcmin: state.fovArcmin,
            epoch_yr: state.epochYr,
            detector: state.detector,
          },
          source_mode: "hour0_static_fallback_no_coverage",
          matched_target: null,
          patch_timeseries: null,
          frames: [],
          gaia_sources: [],
          spectrum_102: null,
          warnings: ["Backend API unavailable; coordinates outside the 5 bundled Hour-0 fallback targets."],
        },
      };
    }

    const patchTs = decodeStaticDetectorTimeseries(bundle, matched, state.detector);
    const gaiaSources = (matched.gaia_sources || [])
      .map(([sid, ra16, dec16, pmra, pmdec, mag]) => {
        const [raEp, decEp] = propagatePositionDeg(ra16, dec16, pmra, pmdec, state.epochYr - 2016.0);
        return {
          source_id: sid,
          ra_deg: Math.round(raEp * 1e6) / 1e6,
          dec_deg: Math.round(decEp * 1e6) / 1e6,
          phot_g_mean_mag: mag,
          pmra_mas_yr: pmra,
          pmdec_mas_yr: pmdec,
        };
      })
      .filter((s) => angularSepArcmin(matchRaEp, matchDecEp, s.ra_deg, s.dec_deg) <= state.fovArcmin / 2.0 + 0.5)
      .slice(0, 50);

    const frames = (matched.frames || []).map(([coll, obsId, sRa, sDec, band, emMin, emMax, tMin, key]) => {
      const s3Url = key ? `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/${key}` : null;
      const irsaUrl = key ? `https://irsa.ipac.caltech.edu/ibe/data/spherex/${key}` : null;
      return {
        obs_collection: coll,
        obs_id: obsId,
        s_ra: sRa,
        s_dec: sDec,
        energy_bandpassname: band,
        em_min: emMin,
        em_max: emMax,
        t_min: tMin,
        access_url: isSafeRemoteUrl(irsaUrl) ? irsaUrl : null,
        s3_fits_url: isSafeRemoteUrl(s3Url) ? s3Url : null,
      };
    });

    const specOut = matched.spectrum_102
      ? { ...matched.spectrum_102, offline_molecule_readings: matched.molecule_readings }
      : null;

    return {
      data: {
        query: {
          coord_input: state.coord,
          ra_deg: qRa,
          dec_deg: qDec,
          ra_deg_at_epoch: Math.round(matchRaEp * 1e6) / 1e6,
          dec_deg_at_epoch: Math.round(matchDecEp * 1e6) / 1e6,
          fov_arcmin: state.fovArcmin,
          epoch_yr: state.epochYr,
          detector: state.detector,
        },
        source_mode: "hour0_static_fallback",
        matched_target: {
          target_id: matched.target_id,
          name: matched.name,
          object_type: matched.object_type,
          ra_deg_at_epoch: Math.round(matchRaEp * 1e6) / 1e6,
          dec_deg_at_epoch: Math.round(matchDecEp * 1e6) / 1e6,
        },
        patch_timeseries: patchTs,
        frames,
        gaia_sources: gaiaSources,
        spectrum_102: specOut,
        warnings: ["Backend API unavailable; showing bundled ADR-003 Hour-0 static fallback data."],
      },
    };
  }

  function applyUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const rawCoord = params.get("coord");
    if (rawCoord && rawCoord.trim()) state.coord = rawCoord.trim().slice(0, 100);
    const rawFov = params.get("fov") ?? params.get("fov_arcmin");
    if (rawFov !== null) {
      const f = parseStrictNumber(rawFov);
      if (Number.isFinite(f) && f >= 0.5 && f <= 30.0) state.fovArcmin = f;
    }
    const rawEpoch = params.get("epoch") ?? params.get("epoch_yr");
    if (rawEpoch !== null) {
      const ep = parseStrictNumber(rawEpoch);
      if (Number.isFinite(ep) && ep >= 1900 && ep <= 2100) state.epochYr = ep;
    }
    if (params.has("det") && DETECTORS.includes(params.get("det"))) state.detector = params.get("det");
    if (params.has("mode") && ["play", "stack", "difference", "rgb"].includes(params.get("mode"))) {
      state.mode = params.get("mode");
    }
    if (params.has("live")) state.live = ["1", "true"].includes(params.get("live").toLowerCase());
    if (params.has("stretch") && ["asinh", "linear"].includes(params.get("stretch"))) {
      state.stretch = params.get("stretch");
    }
    if (params.has("gaia")) state.showGaia = !["0", "false"].includes(params.get("gaia").toLowerCase());
    if (params.has("mask")) state.showMask = !["0", "false"].includes(params.get("mask").toLowerCase());
    if (params.get("embed") === "1") {
      state.embed = true;
      document.body.classList.add("embed-mode");
    }
    els.coordInput.value = state.coord;
    els.epochInput.value = String(state.epochYr);
    els.liveToggle.checked = state.live;
    els.stretchSelect.value = state.stretch;
    els.gaiaToggle.checked = state.showGaia;
    els.maskToggle.checked = state.showMask;
    const matchedFovOpt = [...els.fovSelect.options].find((o) => Number(o.value) === state.fovArcmin);
    if (matchedFovOpt) {
      els.fovSelect.value = matchedFovOpt.value;
    } else {
      const opt = document.createElement("option");
      opt.value = String(state.fovArcmin);
      opt.textContent = `${state.fovArcmin}′`;
      els.fovSelect.appendChild(opt);
      els.fovSelect.value = opt.value;
    }
  }

  function syncUrlParams() {
    const params = new URLSearchParams();
    params.set("coord", state.coord);
    params.set("fov", String(state.fovArcmin));
    params.set("epoch", String(state.epochYr));
    params.set("det", state.detector);
    params.set("mode", state.mode);
    params.set("live", String(state.live));
    params.set("stretch", state.stretch);
    params.set("gaia", String(state.showGaia));
    params.set("mask", String(state.showMask));
    if (state.embed) params.set("embed", "1");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }

  function syncInputsToState() {
    const fovVal = parseStrictNumber(els.fovSelect.value);
    if (Number.isFinite(fovVal) && fovVal >= 0.5 && fovVal <= 30.0) state.fovArcmin = fovVal;
    const epochVal = parseStrictNumber(els.epochInput.value);
    if (Number.isFinite(epochVal) && epochVal >= 1900 && epochVal <= 2100) state.epochYr = epochVal;
    state.live = els.liveToggle.checked;
  }

  function setActiveButtons() {
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      const on = btn.dataset.mode === state.mode;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", String(on));
    });
    document.querySelectorAll(".det-btn").forEach((btn) => {
      const on = btn.dataset.det === state.detector;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", String(on));
    });
    els.playToggle.textContent = (state.playing && state.mode === "play") ? "Pause" : "Play";
  }

  function percentileRange(grid) {
    if (!Array.isArray(grid)) return [-1, 1];
    const vals = [];
    for (let y = 0; y < grid.length; y++) {
      const row = grid[y];
      if (!Array.isArray(row)) continue;
      for (let x = 0; x < row.length; x++) {
        const v = row[x];
        if (isFiniteNumber(v)) vals.push(v);
      }
    }
    if (vals.length === 0) return [-1, 1];
    vals.sort((a, b) => a - b);
    const lo = vals[Math.floor(vals.length * 0.05)];
    const hi = vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.995))];
    return [lo, hi > lo ? hi : lo + 1.0];
  }

  function scaleFlux(v, lo, hi, stretch) {
    if (!isFiniteNumber(v) || !isFiniteNumber(lo) || !isFiniteNumber(hi) || hi <= lo) return 0.0;
    const t = Math.max(0.0, Math.min(1.0, (v - lo) / (hi - lo)));
    if (stretch === "asinh") {
      return Math.asinh(t * 10.0) / Math.asinh(10.0);
    }
    return t;
  }

  function heatColor(t) {
    const r = Math.round(Math.min(255, 255 * Math.pow(t, 0.72)));
    const g = Math.round(Math.min(255, 255 * Math.pow(t, 1.45)));
    const b = Math.round(Math.min(255, 40 + 200 * Math.pow(t, 2.3)));
    return [r, g, b];
  }

  function drawSkyCanvas() {
    const canvas = els.skyCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    const payload = state.payload;
    if (!payload) return;
    const ts = payload.patch_timeseries;

    if (hasValidFrames(ts)) {
      const ny = ts.frames_by_visit[0].length;
      const nx = ts.frames_by_visit[0][0].length;
      const imgData = ctx.createImageData(nx, ny);
      const out = imgData.data;

      if (state.mode === "rgb" && ts.frames_by_visit.length >= 3) {
        const nV = ts.frames_by_visit.length;
        const midIdx = Math.floor((nV - 1) / 2);
        const gR = ts.frames_by_visit[0];
        const gG = ts.frames_by_visit[midIdx];
        const gB = ts.frames_by_visit[nV - 1];
        const [lo, hi] = percentileRange(Array.isArray(ts.stack) ? ts.stack : gR);
        for (let y = 0; y < ny; y++) {
          for (let x = 0; x < nx; x++) {
            const p = (y * nx + x) * 4;
            const vr = readGridCell(gR, y, x);
            const vg = readGridCell(gG, y, x);
            const vb = readGridCell(gB, y, x);
            if (!isFiniteNumber(vr) || !isFiniteNumber(vg) || !isFiniteNumber(vb)) {
              out[p] = 55; out[p + 1] = 18; out[p + 2] = 28; out[p + 3] = 255;
            } else {
              out[p] = Math.round(scaleFlux(vr, lo, hi, state.stretch) * 255);
              out[p + 1] = Math.round(scaleFlux(vg, lo, hi, state.stretch) * 255);
              out[p + 2] = Math.round(scaleFlux(vb, lo, hi, state.stretch) * 255);
              out[p + 3] = 255;
            }
          }
        }
      } else if (state.mode === "difference" && ts.difference) {
        const grid = ts.difference;
        const [lo, hi] = percentileRange(grid);
        const absMax = Math.max(Math.abs(lo), Math.abs(hi), 1e-3);
        for (let y = 0; y < ny; y++) {
          for (let x = 0; x < nx; x++) {
            const p = (y * nx + x) * 4;
            const v = readGridCell(grid, y, x);
            if (!isFiniteNumber(v)) {
              out[p] = 45; out[p + 1] = 20; out[p + 2] = 45; out[p + 3] = 255;
            } else {
              const s = Math.max(-1, Math.min(1, v / absMax));
              out[p] = s > 0 ? Math.round(32 + s * 223) : 24;
              out[p + 1] = Math.round(28 + (1 - Math.abs(s)) * 20);
              out[p + 2] = s < 0 ? Math.round(32 + (-s) * 223) : 28;
              out[p + 3] = 255;
            }
          }
        }
      } else {
        const idx = Math.min(state.visitIdx, ts.frames_by_visit.length - 1);
        const grid = state.mode === "stack" ? ts.stack : ts.frames_by_visit[idx];
        const [lo, hi] = percentileRange(grid);
        for (let y = 0; y < ny; y++) {
          for (let x = 0; x < nx; x++) {
            const p = (y * nx + x) * 4;
            const v = readGridCell(grid, y, x);
            if (!isFiniteNumber(v)) {
              out[p] = 55; out[p + 1] = 18; out[p + 2] = 28; out[p + 3] = 255;
            } else {
              const [r, g, b] = heatColor(scaleFlux(v, lo, hi, state.stretch));
              out[p] = r; out[p + 1] = g; out[p + 2] = b; out[p + 3] = 255;
            }
          }
        }
      }

      const off = document.createElement("canvas");
      off.width = nx;
      off.height = ny;
      off.getContext("2d").putImageData(imgData, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(off, 0, 0, w, h);

      if (state.showMask && Array.isArray(ts.mask_overlay)) {
        const sx = w / nx;
        const sy = h / ny;
        ctx.strokeStyle = "rgba(248, 113, 113, 0.85)";
        ctx.lineWidth = 1;
        for (let y = 0; y < ny; y++) {
          const mRow = ts.mask_overlay[y];
          if (!Array.isArray(mRow)) continue;
          for (let x = 0; x < nx; x++) {
            if (mRow[x] > 0) {
              ctx.strokeRect(x * sx + 0.5, y * sy + 0.5, sx - 1, sy - 1);
            }
          }
        }
      }

      const nV = ts.frames_by_visit.length;
      const firstId = (ts.visits && ts.visits[0] && ts.visits[0].visit_id) || "V1";
      const midIdx = Math.floor((nV - 1) / 2);
      const midId = (ts.visits && ts.visits[midIdx] && ts.visits[midIdx].visit_id) || `V${midIdx + 1}`;
      const lastId = (ts.visits && ts.visits[nV - 1] && ts.visits[nV - 1].visit_id) || `V${nV}`;
      const visitMeta = (ts.visits && ts.visits[Math.min(state.visitIdx, ts.visits.length - 1)]) || {
        visit_id: "V1",
        epoch_iso: "",
      };
      els.visitLabel.textContent = state.mode === "stack"
        ? "Mean Stack"
        : state.mode === "difference"
          ? (nV >= 2 ? `${lastId} − ${firstId}` : "Difference (needs ≥2 visits)")
          : state.mode === "rgb"
            ? (nV >= 3 ? `RGB (${firstId}/${midId}/${lastId})` : `Single-Visit Fallback (${nV}/3 visits)`)
            : `${visitMeta.visit_id} (${(visitMeta.epoch_iso || "").slice(0, 10)})`;
    } else {
      ctx.strokeStyle = "#1f2e47";
      ctx.lineWidth = 1;
      for (let g = 1; g < 4; g++) {
        ctx.beginPath();
        ctx.moveTo((w * g) / 4, 0);
        ctx.lineTo((w * g) / 4, h);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(0, (h * g) / 4);
        ctx.lineTo(w, (h * g) / 4);
        ctx.stroke();
      }
      ctx.fillStyle = "#93a4bd";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("Astropy/Gaia Sky Footprint (No local pack.bin pixel cutout for this field)", 16, 28);
      els.visitLabel.textContent = "Sky Footprint";
    }

    const centerRa = ts ? ts.center_ra_deg : payload.query.ra_deg;
    const centerDec = ts ? ts.center_dec_deg : payload.query.dec_deg;
    const canvasFovArcmin = ts ? ts.fov_arcmin : payload.query.fov_arcmin;
    const cosd = Math.max(Math.cos((centerDec * Math.PI) / 180.0), 1e-6);
    const pxPerArcmin = w / canvasFovArcmin;
    const projectSky = (raDeg, decDeg) => {
      const dxArcmin = shortestRaDeltaDeg(raDeg, centerRa) * cosd * 60.0;
      const dyArcmin = (decDeg - centerDec) * 60.0;
      return [w / 2 - dxArcmin * pxPerArcmin, h / 2 - dyArcmin * pxPerArcmin];
    };

    // Projected query reticle and requested FOV box
    const [qx, qy] = projectSky(payload.query.ra_deg, payload.query.dec_deg);
    ctx.strokeStyle = "rgba(245, 158, 11, 0.85)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(qx - 12, qy);
    ctx.lineTo(qx + 12, qy);
    ctx.moveTo(qx, qy - 12);
    ctx.lineTo(qx, qy + 12);
    ctx.stroke();

    if (ts && Number.isFinite(payload.query.fov_arcmin) && Math.abs(payload.query.fov_arcmin - canvasFovArcmin) > 0.1) {
      const boxPx = payload.query.fov_arcmin * pxPerArcmin;
      ctx.strokeStyle = "rgba(245, 158, 11, 0.55)";
      ctx.lineWidth = 1;
      if (ctx.setLineDash) ctx.setLineDash([4, 4]);
      ctx.strokeRect(qx - boxPx / 2, qy - boxPx / 2, boxPx, boxPx);
      if (ctx.setLineDash) ctx.setLineDash([]);
    }

    if (
      payload.matched_target &&
      Number.isFinite(payload.matched_target.ra_deg_at_epoch) &&
      Number.isFinite(payload.matched_target.dec_deg_at_epoch)
    ) {
      const [tx, ty] = projectSky(payload.matched_target.ra_deg_at_epoch, payload.matched_target.dec_deg_at_epoch);
      if (Math.hypot(tx - qx, ty - qy) > 1.0) {
        ctx.strokeStyle = "#34d399";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(tx - 8, ty - 8);
        ctx.lineTo(tx + 8, ty + 8);
        ctx.moveTo(tx - 8, ty + 8);
        ctx.lineTo(tx + 8, ty - 8);
        ctx.stroke();
      }
    }

    // Overlay Gaia DR3 stars within FOV
    if (state.showGaia && Array.isArray(payload.gaia_sources)) {
      ctx.strokeStyle = "#38bdf8";
      ctx.fillStyle = "#38bdf8";
      ctx.font = "11px monospace";
      payload.gaia_sources.forEach((star) => {
        const [px, py] = projectSky(star.ra_deg, star.dec_deg);
        if (px >= -10 && px <= w + 10 && py >= -10 && py <= h + 10) {
          ctx.beginPath();
          ctx.arc(px, py, 6, 0, Math.PI * 2);
          ctx.stroke();
        }
      });
    }
  }

  function drawMatrixCanvas() {
    const canvas = els.matrixCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);
    const frames = (state.payload && state.payload.frames) || [];
    const pts = frames.filter((f) => Number.isFinite(f.t_min) && Number.isFinite(f.em_min));
    if (pts.length === 0) {
      ctx.fillStyle = "#93a4bd";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("No SPHEREx observation metadata rows matched this sky query.", 16, 40);
      return;
    }
    const minT = Math.min(...pts.map((p) => p.t_min));
    const maxT = Math.max(...pts.map((p) => p.t_min));
    const spanT = Math.max(maxT - minT, 1.0);
    const padL = 42;
    const padR = 16;
    const padT = 16;
    const padB = 24;

    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, w - padL - padR, h - padT - padB);
    ctx.fillStyle = "#93a4bd";
    ctx.font = "11px monospace";
    ctx.fillText("5.0um", 4, padT + 10);
    ctx.fillText("0.75", 4, h - padB);
    ctx.fillText(`MJD ${minT.toFixed(0)}`, padL, h - 6);
    ctx.fillText(`MJD ${maxT.toFixed(0)}`, w - padR - 70, h - 6);

    pts.forEach((p) => {
      const wlUm = p.em_min > 1e-4 ? p.em_min : p.em_min * 1e6;
      const wl = Math.max(0.7, Math.min(5.1, wlUm > 20 ? wlUm / 1e6 : wlUm));
      const x = padL + ((p.t_min - minT) / spanT) * (w - padL - padR);
      const y = h - padB - ((wl - 0.7) / 4.4) * (h - padT - padB);
      ctx.fillStyle = p.obs_collection && p.obs_collection.includes("qr3") ? "#f59e0b" : "#38bdf8";
      ctx.fillRect(x - 2, y - 2, 4, 4);
    });
  }

  function appendMoleculeMessage(title, message, isRefused) {
    const card = document.createElement("div");
    card.className = "mol-item";
    const nameEl = document.createElement("div");
    nameEl.className = "mol-name";
    nameEl.textContent = title;
    const valEl = document.createElement("div");
    valEl.className = isRefused ? "mol-val mol-refused" : "mol-val";
    valEl.textContent = message;
    card.append(nameEl, valEl);
    els.moleculeList.appendChild(card);
  }

  function renderMoleculeReadings(mr, spec, classification) {
    if (classification && classification.all_data) {
      const ad = classification.all_data;
      const nov = classification.novelty ? classification.novelty.status : "N/A";
      const conf = Number.isFinite(Number(ad.confidence)) ? Number(ad.confidence).toFixed(2) : "N/A";
      appendMoleculeMessage(
        "M2/M3 Classifier (Template+Tree)",
        `${ad.top_class} (conf=${conf}, novelty=${nov})`,
        ad.top_class === "Unclassified"
      );
    }
    if (!mr) return;
    if (mr.status === "REFUSED") {
      appendMoleculeMessage("Molecule Readings Refused", mr.refusal_reason || "Refused by safety rules", true);
      return;
    }
    Object.entries(mr.features || {}).forEach(([fname, info]) => {
      if (info.status === "MEASURED") {
        const msg = info.uncertainty_available && Number.isFinite(info.p84) && Number.isFinite(info.p16)
          ? `tau=${Number(info.integrated_tau).toFixed(3)} ± ${((info.p84 - info.p16) / 2).toFixed(3)}`
          : `tau=${Number(info.integrated_tau).toFixed(3)} (no flux_err)`;
        appendMoleculeMessage(fname, msg, false);
      } else {
        appendMoleculeMessage(fname, info.refusal_reason || "Refused", true);
      }
    });
  }

  async function drawSpectrumAndMolecules(seq, signal) {
    const canvas = els.spectrumCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    const spec = state.payload && state.payload.spectrum_102;
    els.moleculeList.replaceChildren();
    if (!spec || !Array.isArray(spec.flux_uJy) || spec.flux_uJy.length !== 102) {
      els.spectrumHeading.textContent = "102-Band Spectrum & Layer-1 Molecule Readings (No cached spectrum at coordinate)";
      ctx.fillStyle = "#93a4bd";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("Select one of the 5 test targets or a WISE 0855 patch to inspect 102-band spectra.", 16, 42);
      return;
    }

    els.spectrumHeading.textContent = `102-Band Spectrum & Layer-1 Molecule Readings — ${spec.label}`;
    const wl = spec.wavelength_um;
    const fl = spec.flux_uJy;
    const finiteFl = fl.filter((v) => v !== null && v !== undefined && Number.isFinite(v));
    const minWl = wl[0];
    const maxWl = wl[wl.length - 1];
    const maxFl = finiteFl.length ? Math.max(...finiteFl, 1.0) : 1.0;
    const minFl = finiteFl.length ? Math.min(...finiteFl, 0.0) : 0.0;
    const spanFl = Math.max(maxFl - minFl, 1e-3);
    const padL = 44;
    const padR = 14;
    const padT = 16;
    const padB = 24;

    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, w - padL - padR, h - padT - padB);
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    let pathStarted = false;
    fl.forEach((v, idx) => {
      if (v === null || v === undefined || !Number.isFinite(v)) {
        pathStarted = false;
        return;
      }
      const x = padL + ((wl[idx] - minWl) / (maxWl - minWl)) * (w - padL - padR);
      const y = h - padB - ((v - minFl) / spanFl) * (h - padT - padB);
      if (!pathStarted) {
        ctx.moveTo(x, y);
        pathStarted = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    ctx.fillStyle = "#93a4bd";
    ctx.font = "11px monospace";
    ctx.fillText(`${minWl.toFixed(2)}um`, padL, h - 6);
    ctx.fillText(`${maxWl.toFixed(2)}um`, w - padR - 55, h - 6);
    ctx.fillText(`${maxFl.toFixed(1)}`, 4, padT + 10);

    if (state.payload && state.payload.source_mode === "hour0_static_fallback" && spec.offline_molecule_readings) {
      renderMoleculeReadings(spec.offline_molecule_readings, spec, spec.offline_classification);
      return;
    }

    try {
      const reqBody = {
        flux_uJy: fl,
        blend_share: spec.blend_share ?? 0.0,
        is_variable: Boolean(spec.is_variable || spec.target_is_variable),
      };
      if (Array.isArray(spec.flux_err_uJy) && spec.flux_err_uJy.length === 102) {
        reqBody.flux_err_uJy = spec.flux_err_uJy;
      }
      const fetchOpts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      };
      if (signal) fetchOpts.signal = signal;
      const resp = await fetch("/api/analyze/spectrum", fetchOpts);
      if (seq !== state.querySeq) return;
      if (!resp.ok) {
        if ((resp.status === 404 || resp.status >= 500) && spec.offline_molecule_readings) {
          renderMoleculeReadings(spec.offline_molecule_readings, spec, spec.offline_classification);
          return;
        }
        appendMoleculeMessage("Layer-1 Analysis Unavailable", `/api/analyze/spectrum returned HTTP ${resp.status}`, true);
        return;
      }
      const data = await resp.json();
      if (seq !== state.querySeq) return;
      renderMoleculeReadings(data.molecule_readings, spec, data.classification);
    } catch (err) {
      if (err && err.name === "AbortError") return;
      if (seq !== state.querySeq) return;
      if (spec.offline_molecule_readings) {
        renderMoleculeReadings(spec.offline_molecule_readings, spec, spec.offline_classification);
        return;
      }
      appendMoleculeMessage("Layer-1 Analysis Unavailable", "Could not reach /api/analyze/spectrum; spectrum chart remains visible.", true);
    }
  }

  function renderFramesTable() {
    els.framesTbody.replaceChildren();
    const frames = (state.payload && state.payload.frames) || [];
    const totalFrames = Number.isFinite(state.payload && state.payload.total_matching_frames)
      ? state.payload.total_matching_frames
      : frames.length;
    const shown = Math.min(frames.length, 120);
    els.framesHeading.textContent = totalFrames > shown
      ? `Observation Matrix & Matching SPHEREx Frames (showing ${shown} of ${totalFrames})`
      : `Observation Matrix & Matching SPHEREx Frames (${totalFrames})`;
    frames.slice(0, 120).forEach((fr) => {
      const tr = document.createElement("tr");
      const tdColl = document.createElement("td");
      tdColl.textContent = fr.obs_collection || "";
      const tdId = document.createElement("td");
      tdId.textContent = fr.obs_id || "";
      const tdBand = document.createElement("td");
      tdBand.textContent = fr.energy_bandpassname || (Number.isFinite(fr.em_min) ? `${fr.em_min}` : "");
      const tdMjd = document.createElement("td");
      tdMjd.textContent = Number.isFinite(fr.t_min) ? fr.t_min.toFixed(2) : "";
      const tdRaDec = document.createElement("td");
      tdRaDec.textContent = Number.isFinite(fr.s_ra) && Number.isFinite(fr.s_dec)
        ? `${fr.s_ra.toFixed(3)}, ${fr.s_dec.toFixed(3)}`
        : "";
      const tdLink = document.createElement("td");
      const rawUrl = fr.s3_fits_url || fr.access_url || "";
      if (isSafeRemoteUrl(rawUrl)) {
        const a = document.createElement("a");
        a.href = rawUrl;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = fr.s3_fits_url ? "S3 FITS" : "IRSA FITS";
        tdLink.appendChild(a);
      } else {
        tdLink.textContent = "-";
      }
      tr.append(tdColl, tdId, tdBand, tdMjd, tdRaDec, tdLink);
      els.framesTbody.appendChild(tr);
    });
  }

  async function applySkyPayload(data, seq, signal) {
    state.payload = data;
    const ts = data.patch_timeseries;
    const nVisits = ts && Array.isArray(ts.visits) ? ts.visits.length : 0;
    els.scrubber.max = String(Math.max(0, nVisits - 1));
    els.scrubber.disabled = nVisits <= 1;
    if (state.visitIdx >= Math.max(1, nVisits)) state.visitIdx = 0;
    syncUrlParams();
    els.modeBadge.textContent = data.source_mode || "local";
    const matchMsg = data.matched_target
      ? `Matched ${data.matched_target.name} (${data.matched_target.target_id})`
      : "Arbitrary sky query";
    const warnMsg = data.warnings && data.warnings.length ? ` | Warning: ${data.warnings.join("; ")}` : "";
    setStatus(
      `${matchMsg} | RA ${data.query.ra_deg.toFixed(5)}°, Dec ${data.query.dec_deg.toFixed(5)}° | `
        + `${data.frames.length} SPHEREx frames | ${data.gaia_sources.length} Gaia DR3 stars${warnMsg}`,
      false
    );
    drawSkyCanvas();
    drawMatrixCanvas();
    renderFramesTable();
    await drawSpectrumAndMolecules(seq, signal);
  }

  async function loadSkyQuery() {
    const seq = ++state.querySeq;
    if (state.abortController) state.abortController.abort();
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    state.abortController = controller;
    const signal = controller ? controller.signal : undefined;

    setStatus(`Querying "${state.coord}" (${state.detector}, FOV ${state.fovArcmin}', epoch ${state.epochYr})...`, false);
    const params = new URLSearchParams({
      coord: state.coord,
      fov_arcmin: String(state.fovArcmin),
      epoch_yr: String(state.epochYr),
      detector: state.detector,
      live: String(state.live),
      frame_limit: "300",
    });
    let allowOfflineFallback = false;
    let rejectionDetail = null;
    try {
      const resp = await fetch(`/api/sky/timeseries?${params.toString()}`, signal ? { signal } : undefined);
      if (seq !== state.querySeq) return;
      if (!resp.ok && (resp.status === 404 || resp.status >= 500)) {
        allowOfflineFallback = true;
      } else {
        const data = await resp.json();
        if (seq !== state.querySeq) return;
        if (!resp.ok) {
          rejectionDetail = data.detail || `Query rejected (HTTP ${resp.status})`;
          setStatus(rejectionDetail, true);
          return;
        }
        await applySkyPayload(data, seq, signal);
        return;
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
      if (seq !== state.querySeq) return;
      allowOfflineFallback = true;
    }

    if (allowOfflineFallback) {
      const offline = resolveOfflineSkyPayload();
      if (offline && offline.data) {
        await applySkyPayload(offline.data, seq, signal);
        return;
      }
      if (offline && offline.error) {
        setStatus(offline.error, true);
        return;
      }
    }
    setStatus(rejectionDetail || "Failed to fetch /api/sky/timeseries from backend API.", true);
  }

  function startLoop() {
    if (state.timerId !== null) window.clearInterval(state.timerId);
    state.timerId = window.setInterval(() => {
      const ts = state.payload && state.payload.patch_timeseries;
      const nVisits = ts && Array.isArray(ts.visits) ? ts.visits.length : 0;
      if (state.playing && state.mode === "play" && nVisits > 1) {
        state.visitIdx = (state.visitIdx + 1) % nVisits;
        els.scrubber.value = String(state.visitIdx);
        drawSkyCanvas();
      }
    }, 750);
  }

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const nextCoord = els.coordInput.value.trim();
    if (!nextCoord) {
      setStatus("Please enter a target name or sky coordinates.", true);
      return;
    }
    state.coord = nextCoord;
    syncInputsToState();
    loadSkyQuery();
  });

  els.fovSelect.addEventListener("change", () => {
    syncInputsToState();
    loadSkyQuery();
  });

  els.liveToggle.addEventListener("change", () => {
    syncInputsToState();
    loadSkyQuery();
  });

  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.coord = btn.dataset.coord;
      els.coordInput.value = state.coord;
      syncInputsToState();
      loadSkyQuery();
    });
  });

  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.mode = btn.dataset.mode;
      setActiveButtons();
      syncUrlParams();
      drawSkyCanvas();
    });
  });

  async function switchDetectorOnly() {
    const ts = state.payload && state.payload.patch_timeseries;
    if (!ts || !ts.target_id) {
      return loadSkyQuery();
    }
    if (state.payload.source_mode === "hour0_static_fallback") {
      const offline = resolveOfflineSkyPayload();
      if (offline && offline.data) {
        await applySkyPayload(offline.data, ++state.querySeq);
        return;
      }
    }
    const seq = ++state.querySeq;
    const params = new URLSearchParams({
      detector: state.detector,
      target_id: ts.target_id,
    });
    try {
      const resp = await fetch(`/api/patch/timeseries?${params.toString()}`);
      if (seq !== state.querySeq) return;
      if (resp && resp.ok) {
        const nextTs = await resp.json();
        if (seq !== state.querySeq) return;
        if (nextTs && Array.isArray(nextTs.frames_by_visit)) {
          state.payload.patch_timeseries = nextTs;
          if (state.payload.query) state.payload.query.detector = state.detector;
          syncUrlParams();
          drawSkyCanvas();
          return;
        }
      }
    } catch (_err) {
      // Fall back to full sky query / offline fallback if patch endpoint is unreachable
    }
    return loadSkyQuery();
  }

  document.querySelectorAll(".det-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.detector = btn.dataset.det;
      syncInputsToState();
      setActiveButtons();
      switchDetectorOnly();
    });
  });

  els.playToggle.addEventListener("click", () => {
    if (state.mode !== "play") {
      state.mode = "play";
      state.playing = true;
      setActiveButtons();
      syncUrlParams();
      drawSkyCanvas();
      return;
    }
    state.playing = !state.playing;
    setActiveButtons();
  });

  els.scrubber.addEventListener("input", () => {
    state.playing = false;
    const v = Number(els.scrubber.value);
    state.visitIdx = Number.isInteger(v) && v >= 0 ? v : 0;
    if (state.mode !== "play") state.mode = "play";
    setActiveButtons();
    syncUrlParams();
    drawSkyCanvas();
  });

  els.stretchSelect.addEventListener("change", () => {
    state.stretch = els.stretchSelect.value;
    syncUrlParams();
    drawSkyCanvas();
  });

  els.gaiaToggle.addEventListener("change", () => {
    state.showGaia = els.gaiaToggle.checked;
    syncUrlParams();
    drawSkyCanvas();
  });

  els.maskToggle.addEventListener("change", () => {
    state.showMask = els.maskToggle.checked;
    syncUrlParams();
    drawSkyCanvas();
  });

  els.skyCanvas.addEventListener("mousemove", (ev) => {
    const ts = state.payload && state.payload.patch_timeseries;
    if (!hasValidFrames(ts)) {
      return;
    }
    const rect = els.skyCanvas.getBoundingClientRect();
    if (
      !rect || !isFiniteNumber(rect.width) || !isFiniteNumber(rect.height)
      || rect.width <= 0 || rect.height <= 0
      || !isFiniteNumber(ev.clientX) || !isFiniteNumber(ev.clientY)
    ) {
      return;
    }
    const ny = ts.frames_by_visit[0].length;
    const nx = ts.frames_by_visit[0][0].length;
    const px = Math.floor(((ev.clientX - rect.left) / rect.width) * nx);
    const py = Math.floor(((ev.clientY - rect.top) / rect.height) * ny);
    if (!Number.isInteger(px) || !Number.isInteger(py) || px < 0 || px >= nx || py < 0 || py >= ny) return;
    const rawMask = readGridCell(ts.mask_overlay, py, px);
    const maskVal = isFiniteNumber(rawMask) ? rawMask : 0;
    if (state.mode === "rgb" && ts.frames_by_visit.length >= 3) {
      const nV = ts.frames_by_visit.length;
      const fmt = (v) => (isFiniteNumber(v) ? v.toFixed(2) : "NaN");
      const vR = readGridCell(ts.frames_by_visit[0], py, px);
      const vG = readGridCell(ts.frames_by_visit[Math.floor((nV - 1) / 2)], py, px);
      const vB = readGridCell(ts.frames_by_visit[nV - 1], py, px);
      els.pixelReadout.textContent = `Pixel (${px}, ${py}) | RGB Flux: ${fmt(vR)}/${fmt(vG)}/${fmt(vB)} rel | Mask bits: ${maskVal}`;
      return;
    }
    const grid = state.mode === "stack"
      ? ts.stack
      : (state.mode === "difference" && ts.difference)
        ? ts.difference
        : ts.frames_by_visit[Math.min(state.visitIdx, ts.frames_by_visit.length - 1)];
    const val = readGridCell(grid, py, px);
    const valText = isFiniteNumber(val) ? `${val.toFixed(3)} rel` : "MASKED (NaN)";
    els.pixelReadout.textContent = `Pixel (${px}, ${py}) | Flux: ${valText} | Mask bits: ${maskVal}`;
  });

  els.copyUrlBtn.addEventListener("click", async () => {
    const typed = els.coordInput.value.trim();
    if (typed) state.coord = typed;
    syncInputsToState();
    syncUrlParams();
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
      setStatus("Clipboard API unavailable; updated browser URL bar instead.", true);
      return;
    }
    try {
      await navigator.clipboard.writeText(window.location.href);
      setStatus("Share URL copied to clipboard.", false);
    } catch (_err) {
      setStatus("Could not access clipboard; updated browser URL bar instead.", true);
    }
  });

  applyUrlParams();
  setActiveButtons();
  startLoop();
  loadSkyQuery();
})();
