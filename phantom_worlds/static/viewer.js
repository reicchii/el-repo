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
    speedMs: 750,
    live: false,
    showGaia: true,
    showMask: true,
    invert: false,
    followMotion: false,
    injectTestSource: false,
    embed: false,
    payload: null,
    tierAMetrics: null,
    proofSummary: null,
    auxDetCache: {},
    matrixMeta: null,
    activeFieldId: null,
    fieldLayer: "image",
    fieldData: null,
    fieldFadeProgress: 1.0,
    fieldFadeFrom: "image",
    fieldFadeRaf: null,
    searchCategories: [],
    searchFieldScope: "all",
    searchMinSnr: 5,
    searchMaxBlend: 1.0,
    searchOnlyUnexplained: false,
    searchSortBy: "priority",
    searchResults: [],
    selectedFieldSource: null,
    lastModelCard: null,
    showSearchedDepth: false,
    searchedDepth: null,
    fieldCases: [],
    retroMovers: [],
    b7Summary: null,
    caseStateFilter: "all",
    selectedCaseId: null,
    caseOverrides: {},
    proofReportV2: null,
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
    lightcurveCanvas: document.getElementById("lightcurve-canvas"),
    playToggle: document.getElementById("play-toggle"),
    scrubber: document.getElementById("visit-scrubber"),
    visitLabel: document.getElementById("visit-label"),
    stretchSelect: document.getElementById("stretch-select"),
    speedSelect: document.getElementById("speed-select"),
    gaiaToggle: document.getElementById("gaia-overlay-toggle"),
    maskToggle: document.getElementById("mask-overlay-toggle"),
    invertToggle: document.getElementById("invert-toggle"),
    followMotionToggle: document.getElementById("follow-motion-toggle"),
    injectToggle: document.getElementById("inject-toggle"),
    exportPngBtn: document.getElementById("export-png-btn"),
    exportCsvBtn: document.getElementById("export-csv-btn"),
    externalLinks: document.getElementById("external-links"),
    motionSummary: document.getElementById("motion-summary"),
    changeSpectrumList: document.getElementById("change-spectrum-list"),
    ssoInput: document.getElementById("sso-input"),
    ssoQueryBtn: document.getElementById("sso-query-btn"),
    ssoStatus: document.getElementById("sso-status"),
    proofBody: document.getElementById("proof-summary-body"),
    pixelReadout: document.getElementById("pixel-readout"),
    moleculeList: document.getElementById("molecule-list"),
    framesTbody: document.getElementById("frames-tbody"),
    framesHeading: document.getElementById("frames-heading"),
    spectrumHeading: document.getElementById("spectrum-heading"),
    copyUrlBtn: document.getElementById("copy-url-btn"),
    removeKnownRow: document.getElementById("remove-known-row"),
    searchCoverageNote: document.getElementById("search-coverage-note"),
    searchMatchCount: document.getElementById("search-match-count"),
    searchFieldScope: document.getElementById("search-field-scope"),
    searchMinSnr: document.getElementById("search-min-snr"),
    searchMinSnrVal: document.getElementById("search-min-snr-val"),
    searchMaxBlend: document.getElementById("search-max-blend"),
    searchMaxBlendVal: document.getElementById("search-max-blend-val"),
    searchUnexplainedOnly: document.getElementById("search-unexplained-only"),
    searchSortSelect: document.getElementById("search-sort-select"),
    searchResultsList: document.getElementById("search-results-list"),
    identityCard: document.getElementById("identity-v2-card"),
    identityTitle: document.getElementById("identity-v2-title"),
    identityHeader: document.getElementById("identity-v2-header"),
    identityBands: document.getElementById("identity-v2-bands"),
    identityStripCanvas: document.getElementById("identity-strip-canvas"),
    identityTop3: document.getElementById("identity-v2-top3"),
    identityChecks: document.getElementById("identity-v2-checks"),
    identityMeta: document.getElementById("identity-v2-meta"),
    modelCardOpenBtn: document.getElementById("model-card-open-btn"),
    modelCardModal: document.getElementById("model-card-modal"),
    modelCardCloseBtn: document.getElementById("model-card-close-btn"),
    modelCardBody: document.getElementById("model-card-body"),
    searchedDepthToggle: document.getElementById("searched-depth-layer-toggle"),
    casesCountBadge: document.getElementById("cases-count-badge"),
    casesList: document.getElementById("signals-cases-list"),
    caseDetailBox: document.getElementById("case-detail-box"),
    caseDetailTitle: document.getElementById("case-detail-title"),
    caseDetailSummary: document.getElementById("case-detail-summary"),
    caseDetailChecks: document.getElementById("case-detail-checks"),
    caseFlagArtefactBtn: document.getElementById("case-flag-artefact-btn"),
    caseMarkExplainedBtn: document.getElementById("case-mark-explained-btn"),
    caseReopenBtn: document.getElementById("case-reopen-btn"),
    retroSummary: document.getElementById("retro-prediction-summary"),
    retroList: document.getElementById("retro-prediction-list"),
    proofV2Extra: document.getElementById("proof-v2-extra"),
    proofReportCardWrap: document.getElementById("proof-report-card-wrap"),
    recoveryCurveCanvas: document.getElementById("recovery-curve-canvas"),
    proofLadderWrap: document.getElementById("proof-ladder-wrap"),
    proofPlanetXStatement: document.getElementById("proof-planet-x-statement"),
    proofCreditsWrap: document.getElementById("proof-credits-wrap"),
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
          pm_ra_mas_yr: matched.pm_ra_mas_yr,
          pm_dec_mas_yr: matched.pm_dec_mas_yr,
        },
        patch_timeseries: patchTs,
        frames,
        gaia_sources: gaiaSources,
        spectrum_102: specOut,
        offline_tier_a_metrics: matched.tier_a_metrics || null,
        offline_proof_summary: bundle.proof_summary || null,
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
    if (params.has("mode") && ["play", "stack", "difference", "coldiff", "rgb"].includes(params.get("mode"))) {
      state.mode = params.get("mode");
    }
    if (params.has("live")) state.live = ["1", "true"].includes(params.get("live").toLowerCase());
    if (params.has("stretch") && ["asinh", "linear"].includes(params.get("stretch"))) {
      state.stretch = params.get("stretch");
    }
    if (params.has("speed")) {
      const spd = Number(params.get("speed"));
      if ([300, 750, 1200].includes(spd)) state.speedMs = spd;
    }
    if (params.has("invert")) state.invert = ["1", "true"].includes(params.get("invert").toLowerCase());
    if (params.has("follow")) state.followMotion = ["1", "true"].includes(params.get("follow").toLowerCase());
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
    if (els.speedSelect) els.speedSelect.value = String(state.speedMs);
    if (els.invertToggle) els.invertToggle.checked = state.invert;
    if (els.followMotionToggle) els.followMotionToggle.checked = state.followMotion;
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
    if (state.speedMs !== 750) params.set("speed", String(state.speedMs));
    if (state.invert) params.set("invert", "1");
    if (state.followMotion) params.set("follow", "1");
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
    document.querySelectorAll(".field-btn").forEach((btn) => {
      const on = Boolean(state.activeFieldId) && btn.dataset.field === state.activeFieldId;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", String(on));
    });
    if (els.removeKnownRow) {
      els.removeKnownRow.hidden = !state.activeFieldId;
    }
    document.querySelectorAll(".rmknown-btn").forEach((btn) => {
      const on = btn.dataset.layer === state.fieldLayer;
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

  function heatColor(t, invert) {
    if (invert) {
      const c = Math.round((1.0 - t) * 245);
      return [c, c, Math.min(255, c + 10)];
    }
    const r = Math.round(Math.min(255, 255 * Math.pow(t, 0.72)));
    const g = Math.round(Math.min(255, 255 * Math.pow(t, 1.45)));
    const b = Math.round(Math.min(255, 40 + 200 * Math.pow(t, 2.3)));
    return [r, g, b];
  }

  function medianNumeric(arr) {
    if (!arr || !arr.length) return 0.0;
    const sorted = arr.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 1 ? sorted[mid] : 0.5 * (sorted[mid - 1] + sorted[mid]);
  }

  function getTargetProperMotion(payload) {
    if (!payload) return [0.0, 0.0];
    const mt = payload.matched_target || {};
    if (isFiniteNumber(mt.pm_ra_mas_yr) && isFiniteNumber(mt.pm_dec_mas_yr)) {
      return [mt.pm_ra_mas_yr, mt.pm_dec_mas_yr];
    }
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
    if (bundle && bundle.targets && mt.target_id && bundle.targets[mt.target_id]) {
      const bt = bundle.targets[mt.target_id];
      return [Number(bt.pm_ra_mas_yr || 0), Number(bt.pm_dec_mas_yr || 0)];
    }
    if (state.tierAMetrics && state.tierAMetrics.motion) {
      const m = state.tierAMetrics.motion;
      if (isFiniteNumber(m.measured_pm_ra_mas_yr) && isFiniteNumber(m.measured_pm_dec_mas_yr)) {
        return [m.measured_pm_ra_mas_yr, m.measured_pm_dec_mas_yr];
      }
    }
    return [0.0, 0.0];
  }

  function getVisitShiftPx(payload, ts, visitIdx) {
    if (!ts || !Array.isArray(ts.visits) || ts.visits.length < 2) return [0, 0];
    const [pmra, pmdec] = getTargetProperMotion(payload);
    const mjd0 = Number(ts.visits[0] && ts.visits[0].mjd);
    const mjdV = Number(ts.visits[visitIdx] && ts.visits[visitIdx].mjd);
    if (!isFiniteNumber(mjd0) || !isFiniteNumber(mjdV)) return [0, 0];
    const dtYr = (mjdV - mjd0) / 365.25;
    const pxScale = isFiniteNumber(ts.pixel_scale_arcsec) ? ts.pixel_scale_arcsec : 6.15;
    // East-left/North-up WCS: +RA moves -x, +Dec moves -y; sample shifted source back to visit 0.
    const dx = Math.round((-(pmra / 1000.0) * dtYr) / pxScale);
    const dy = Math.round((-(pmdec / 1000.0) * dtYr) / pxScale);
    return [dx, dy];
  }

  function shiftGrid(grid, dx, dy) {
    if (!Array.isArray(grid) || (dx === 0 && dy === 0)) return grid;
    const ny = grid.length;
    const nx = grid[0] ? grid[0].length : 0;
    return grid.map((_r, y) =>
      Array.from({ length: nx }, (_c, x) => readGridCell(grid, y + dy, x + dx))
    );
  }

  function computeFollowMotionStack(payload, ts) {
    const nV = ts.frames_by_visit.length;
    const ny = ts.frames_by_visit[0].length;
    const nx = ts.frames_by_visit[0][0].length;
    const shifted = ts.frames_by_visit.map((g, vIdx) => {
      const [dx, dy] = getVisitShiftPx(payload, ts, vIdx);
      return shiftGrid(g, dx, dy);
    });
    return Array.from({ length: ny }, (_r, y) =>
      Array.from({ length: nx }, (_c, x) => {
        const vals = [];
        for (let v = 0; v < nV; v++) {
          const val = readGridCell(shifted[v], y, x);
          if (isFiniteNumber(val)) vals.push(val);
        }
        return vals.length ? medianNumeric(vals) : null;
      })
    );
  }

  function getCachedDetectorTs(payload, detId) {
    const ts = payload && payload.patch_timeseries;
    if (ts && ts.detector === detId) return ts;
    const tid = (payload && payload.matched_target && payload.matched_target.target_id) || (ts && ts.target_id);
    if (tid && state.auxDetCache[`${tid}:${detId}`]) {
      return state.auxDetCache[`${tid}:${detId}`];
    }
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
    if (bundle && bundle.targets && tid && bundle.targets[tid]) {
      return decodeStaticDetectorTimeseries(bundle, bundle.targets[tid], detId);
    }
    return null;
  }

  async function ensureColourDiffGrids() {
    const payload = state.payload;
    if (!payload) return;
    const tid = (payload.matched_target && payload.matched_target.target_id)
      || (payload.patch_timeseries && payload.patch_timeseries.target_id);
    if (!tid) return;
    const seq = state.querySeq;
    const needed = ["D4", "D6"].filter((d) => !getCachedDetectorTs(payload, d));
    if (!needed.length) return;
    await Promise.all(
      needed.map(async (d) => {
        try {
          const r = await fetch(`/api/patch/timeseries?detector=${d}&target_id=${encodeURIComponent(tid)}`);
          if (r && r.ok) {
            const j = await r.json();
            if (j && Array.isArray(j.stack)) {
              state.auxDetCache[`${tid}:${d}`] = j;
            }
          }
        } catch (_e) {
          // Offline fallback handled cleanly by getCachedDetectorTs
        }
      })
    );
    if (seq === state.querySeq && state.mode === "coldiff") {
      drawSkyCanvas();
    }
  }

  function buildColourDiffGrid(payload) {
    const ts4 = getCachedDetectorTs(payload, "D4");
    const ts6 = getCachedDetectorTs(payload, "D6");
    if (!ts4 || !ts6 || !Array.isArray(ts4.stack) || !Array.isArray(ts6.stack)) return null;
    const ny = ts6.stack.length;
    const nx = ts6.stack[0] ? ts6.stack[0].length : 0;
    const flat4 = [];
    const flat6 = [];
    for (let y = 0; y < ny; y++) {
      for (let x = 0; x < nx; x++) {
        const a = readGridCell(ts4.stack, y, x);
        const b = readGridCell(ts6.stack, y, x);
        if (isFiniteNumber(a)) flat4.push(a);
        if (isFiniteNumber(b)) flat6.push(b);
      }
    }
    const med4 = medianNumeric(flat4);
    const med6 = medianNumeric(flat6);
    return Array.from({ length: ny }, (_r, y) =>
      Array.from({ length: nx }, (_c, x) => {
        const v4 = readGridCell(ts4.stack, y, x);
        const v6 = readGridCell(ts6.stack, y, x);
        return isFiniteNumber(v4) && isFiniteNumber(v6) ? (v6 - med6) - (v4 - med4) : null;
      })
    );
  }

  function injectTestSourceGrid(grid) {
    if (!state.injectTestSource || !Array.isArray(grid) || !grid.length) return grid;
    const ny = grid.length;
    const nx = grid[0] ? grid[0].length : 0;
    const vals = [];
    for (let y = 2; y < ny - 2; y++) {
      for (let x = 2; x < nx - 2; x++) {
        const v = readGridCell(grid, y, x);
        if (isFiniteNumber(v)) vals.push(v);
      }
    }
    if (!vals.length) return grid;
    const med = medianNumeric(vals);
    const absDevs = vals.map((v) => Math.abs(v - med));
    const sigma = Math.max(1e-4, 1.4826 * medianNumeric(absDevs));
    const peak = 5.0 * sigma;
    const cx = Math.round(nx * 0.72);
    const cy = Math.round(ny * 0.28);
    return grid.map((row, y) =>
      row.map((val, x) => {
        if (!isFiniteNumber(val)) return val;
        const r2 = (x - cx) ** 2 + (y - cy) ** 2;
        return r2 <= 25 ? val + peak * Math.exp(-r2 / (2.0 * 1.15 * 1.15)) : val;
      })
    );
  }

  function confidenceWord(prob) {
    const p = Number(prob);
    if (!Number.isFinite(p) || p < 0.5) return "Unclassified";
    if (p < 0.7) return "Possibly";
    if (p < 0.9) return "Probably";
    return "Very likely";
  }

  function buildExternalTelescopeLinks(raDeg, decDeg) {
    if (!Number.isFinite(raDeg) || !Number.isFinite(decDeg)) return [];
    const raStr = raDeg.toFixed(6);
    const decStr = decDeg.toFixed(6);
    const coo = encodeURIComponent(`${raStr} ${decStr}`);
    return [
      { label: "IRSA Finder Chart", href: `https://irsa.ipac.caltech.edu/applications/finderchart/?locstr=${coo}` },
      { label: "SIMBAD", href: `https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=${coo}&Radius=2&Radius.unit=arcmin` },
      { label: "Aladin Lite", href: `https://aladin.cds.unistra.fr/AladinLite/?target=${coo}&fov=0.12` },
    ];
  }

  function csvCell(val) {
    const raw = val === null || val === undefined ? "" : String(val);
    const safe = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  }

  function prefersReducedMotion() {
    return (
      typeof window !== "undefined"
      && typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function resolveFieldLayerGrid(fd, layerName) {
    if (!fd) return null;
    if (layerName === "model") return fd.model_stack;
    if (layerName === "residual") return fd.residual_stack;
    return fd.image_stack;
  }

  function setFieldLayer(nextLayer) {
    if (!["image", "model", "residual"].includes(nextLayer)) return;
    if (state.fieldFadeRaf && typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(state.fieldFadeRaf);
      state.fieldFadeRaf = null;
    }
    const prevLayer = state.fieldLayer;
    state.fieldLayer = nextLayer;
    setActiveButtons();
    const shouldAnimate = (
      state.activeFieldId
      && state.fieldData
      && prevLayer !== nextLayer
      && !prefersReducedMotion()
      && typeof requestAnimationFrame === "function"
      && typeof performance !== "undefined"
    );
    if (!shouldAnimate) {
      state.fieldFadeFrom = nextLayer;
      state.fieldFadeProgress = 1.0;
      drawSkyCanvas();
      return;
    }
    state.fieldFadeFrom = prevLayer;
    state.fieldFadeProgress = 0.0;
    const t0 = performance.now();
    const durationMs = 1000.0;
    const step = (now) => {
      const elapsed = Math.max(0.0, now - t0);
      state.fieldFadeProgress = Math.min(1.0, elapsed / durationMs);
      drawSkyCanvas();
      if (state.fieldFadeProgress < 1.0) {
        state.fieldFadeRaf = requestAnimationFrame(step);
      } else {
        state.fieldFadeRaf = null;
        state.fieldFadeFrom = nextLayer;
      }
    };
    state.fieldFadeRaf = requestAnimationFrame(step);
  }

  function drawFieldSkyCanvas(ctx, w, h) {
    const fd = state.fieldData;
    if (!fd || !Array.isArray(fd.image_stack) || !fd.image_stack.length) return;
    const ny = fd.image_stack.length;
    const nx = fd.image_stack[0].length;
    // Share ONE fixed stretch anchored on the raw sky Image stack across Image, Model, and Residual.
    const [lo, hi] = percentileRange(fd.image_stack);
    const modGrid = fd.model_stack;
    const fromGrid = resolveFieldLayerGrid(fd, state.fieldFadeFrom) || fd.image_stack;
    const toGrid = resolveFieldLayerGrid(fd, state.fieldLayer) || fd.image_stack;
    const t = Math.max(0.0, Math.min(1.0, state.fieldFadeProgress));
    const modMax = Math.max(hi - lo, 1e-4);

    const imgData = ctx.createImageData(nx, ny);
    const out = imgData.data;
    for (let y = 0; y < ny; y++) {
      for (let x = 0; x < nx; x++) {
        const p = (y * nx + x) * 4;
        const vFrom = readGridCell(fromGrid, y, x);
        const vTo = readGridCell(toGrid, y, x);
        const vShow = t >= 0.999 ? vTo : (!isFiniteNumber(vTo) ? vTo : (isFiniteNumber(vFrom) ? vFrom : vTo));
        if (!isFiniteNumber(vShow)) {
          out[p] = 55; out[p + 1] = 18; out[p + 2] = 28; out[p + 3] = 255;
          continue;
        }
        let val = vTo;
        if (t < 0.999 && isFiniteNumber(vFrom)) {
          // Brightness-ordered 1s fade: brightest modeled sources fade first
          const mv = readGridCell(modGrid, y, x);
          const mNorm = isFiniteNumber(mv) ? Math.max(0.0, Math.min(1.0, (mv - lo) / modMax)) : 0.0;
          const localFade = Math.max(0.0, Math.min(1.0, t * 1.45 - (1.0 - mNorm) * 0.45));
          val = vFrom + (vTo - vFrom) * localFade;
        }
        const [r, g, b] = heatColor(scaleFlux(val, lo, hi, state.stretch), state.invert);
        out[p] = r; out[p + 1] = g; out[p + 2] = b; out[p + 3] = 255;
      }
    }
    const off = document.createElement("canvas");
    off.width = nx;
    off.height = ny;
    off.getContext("2d").putImageData(imgData, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off, 0, 0, w, h);

    if (state.showGaia && Array.isArray(fd.fitted_sources)) {
      const sx = w / nx;
      const sy = h / ny;
      ctx.strokeStyle = "rgba(56, 189, 248, 0.72)";
      ctx.lineWidth = 1;
      fd.fitted_sources.slice(0, 80).forEach((s) => {
        if (!isFiniteNumber(s.x_px) || !isFiniteNumber(s.y_px)) return;
        ctx.beginPath();
        ctx.arc((s.x_px + 0.5) * sx, (s.y_px + 0.5) * sy, Math.max(4, sx * 0.7), 0, Math.PI * 2);
        ctx.stroke();
      });
    }
    const sel = state.selectedFieldSource;
    if (sel && sel.field_id === state.activeFieldId && isFiniteNumber(sel.x_px) && isFiniteNumber(sel.y_px)) {
      const sx = w / nx;
      const sy = h / ny;
      const cx = (sel.x_px + 0.5) * sx;
      const cy = (sel.y_px + 0.5) * sy;
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(9, sx * 1.4), 0, Math.PI * 2);
      ctx.moveTo(cx - 14, cy);
      ctx.lineTo(cx + 14, cy);
      ctx.moveTo(cx, cy - 14);
      ctx.lineTo(cx, cy + 14);
      ctx.stroke();
      ctx.fillStyle = "#f59e0b";
      ctx.font = "11px monospace";
      ctx.fillText(sel.source_id || "Selected", Math.min(w - 110, cx + 10), Math.max(14, cy - 10));

      const matchedCase = (state.fieldCases || []).find((c) => c.field_id === state.activeFieldId && c.source_id === sel.source_id);
      const pred = matchedCase && matchedCase.prediction;
      if (pred && isFiniteNumber(pred.predicted_ra_deg) && isFiniteNumber(pred.predicted_dec_deg) && isFiniteNumber(pred.stay_ra_deg) && isFiniteNumber(pred.stay_dec_deg)) {
        const scaleAs = ((fd.fov_arcmin || 6.56) * 60.0) / Math.max(nx, 1);
        const cosd = Math.max(Math.cos((pred.stay_dec_deg * Math.PI) / 180.0), 1e-6);
        const dRaAs = shortestRaDeltaDeg(pred.predicted_ra_deg, pred.stay_ra_deg) * cosd * 3600.0;
        const dDecAs = (pred.predicted_dec_deg - pred.stay_dec_deg) * 3600.0;
        const pxPred = cx - (dRaAs / scaleAs) * sx;
        const pyPred = cy - (dDecAs / scaleAs) * sy;
        ctx.strokeStyle = "#38bdf8";
        if (typeof ctx.setLineDash === "function") ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(pxPred, pyPred);
        ctx.stroke();
        if (typeof ctx.setLineDash === "function") ctx.setLineDash([]);
        ctx.strokeRect(pxPred - 5, pyPred - 5, 10, 10);
        ctx.fillStyle = "#38bdf8";
        ctx.fillText("Locked +183d", Math.min(w - 115, pxPred + 8), Math.max(26, pyPred + 4));
      }
    }

    if (state.showSearchedDepth) {
      const sdRoot = state.searchedDepth || ((globalThis.__PHANTOM_STATIC_FALLBACK__ || {}).searched_depth);
      const sf = sdRoot && sdRoot.fields && sdRoot.fields[state.activeFieldId];
      const detS = sf && sf.detectors && sf.detectors[fd.detector];
      const d90 = detS && isFiniteNumber(detS.depth_ab_90) ? `${detS.depth_ab_90.toFixed(2)} AB` : "below 90%";
      const d50 = detS && isFiniteNumber(detS.depth_ab_50) ? `${detS.depth_ab_50.toFixed(2)} AB` : "n/a";
      const sFrac = detS && isFiniteNumber(detS.searchable_area_frac) ? `${Math.round(detS.searchable_area_frac * 100)}%` : "n/a";
      // Subtle unsearched edge vignette (detector edges excluded from injection grid)
      const edgePx = Math.round((6.0 / Math.max(nx, 1)) * w);
      ctx.fillStyle = "rgba(15, 23, 42, 0.35)";
      ctx.fillRect(0, 0, w, edgePx);
      ctx.fillRect(0, h - edgePx, w, edgePx);
      ctx.fillRect(0, edgePx, edgePx, h - 2 * edgePx);
      ctx.fillRect(w - edgePx, edgePx, edgePx, h - 2 * edgePx);

      ctx.fillStyle = "rgba(11, 16, 27, 0.88)";
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 1;
      ctx.fillRect(10, 10, 290, 68);
      ctx.strokeRect(10, 10, 290, 68);
      ctx.fillStyle = "#e2e8f0";
      ctx.font = "11px monospace";
      ctx.fillText(`Searched depth (${fd.detector}) · area ${sFrac}`, 18, 28);
      ctx.fillStyle = "#38bdf8";
      ctx.fillText(`90%: ${d90} | 50%: ${d50}`, 18, 46);
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(`FOV ${(sf && sf.fov_arcmin) || 6.56}' · 500 AU shift ~800" (~130 px)`, 18, 64);
    }

    const layerLabel = state.fieldLayer === "model" ? "Model" : state.fieldLayer === "residual" ? "Residual" : "Image";
    if (els.visitLabel) {
      els.visitLabel.textContent = `${fd.field_name} · ${fd.detector} · ${layerLabel} (stretch [${lo.toFixed(2)}, ${hi.toFixed(2)}])`;
    }
  }

  function drawSkyCanvas() {
    const canvas = els.skyCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    if (state.activeFieldId && state.fieldData) {
      drawFieldSkyCanvas(ctx, w, h);
      return;
    }

    const payload = state.payload;
    if (!payload) return;
    const ts = payload.patch_timeseries;

    if (hasValidFrames(ts)) {
      const ny = ts.frames_by_visit[0].length;
      const nx = ts.frames_by_visit[0][0].length;
      const imgData = ctx.createImageData(nx, ny);
      const out = imgData.data;

      let coldiffMissing = false;
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
              const cR = Math.round(scaleFlux(vr, lo, hi, state.stretch) * 255);
              const cG = Math.round(scaleFlux(vg, lo, hi, state.stretch) * 255);
              const cB = Math.round(scaleFlux(vb, lo, hi, state.stretch) * 255);
              out[p] = state.invert ? 255 - cR : cR;
              out[p + 1] = state.invert ? 255 - cG : cG;
              out[p + 2] = state.invert ? 255 - cB : cB;
              out[p + 3] = 255;
            }
          }
        }
      } else if (state.mode === "coldiff") {
        let diffGrid = buildColourDiffGrid(payload);
        if (!diffGrid) {
          coldiffMissing = true;
          ensureColourDiffGrids();
          diffGrid = injectTestSourceGrid(ts.stack);
        } else {
          diffGrid = injectTestSourceGrid(diffGrid);
        }
        const [lo, hi] = percentileRange(diffGrid);
        const absMax = Math.max(Math.abs(lo), Math.abs(hi), 1e-3);
        for (let y = 0; y < ny; y++) {
          for (let x = 0; x < nx; x++) {
            const p = (y * nx + x) * 4;
            const v = readGridCell(diffGrid, y, x);
            if (!isFiniteNumber(v)) {
              out[p] = 45; out[p + 1] = 20; out[p + 2] = 45; out[p + 3] = 255;
            } else {
              const s = Math.max(-1, Math.min(1, v / absMax));
              const r = s > 0 ? Math.round(32 + s * 223) : 24;
              const g = Math.round(28 + (1 - Math.abs(s)) * 20);
              const b = s < 0 ? Math.round(32 + (-s) * 223) : 28;
              out[p] = state.invert ? 255 - r : r;
              out[p + 1] = state.invert ? 255 - g : g;
              out[p + 2] = state.invert ? 255 - b : b;
              out[p + 3] = 255;
            }
          }
        }
      } else if (state.mode === "difference" && ts.difference) {
        const grid = injectTestSourceGrid(ts.difference);
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
              const r = s > 0 ? Math.round(32 + s * 223) : 24;
              const g = Math.round(28 + (1 - Math.abs(s)) * 20);
              const b = s < 0 ? Math.round(32 + (-s) * 223) : 28;
              out[p] = state.invert ? 255 - r : r;
              out[p + 1] = state.invert ? 255 - g : g;
              out[p + 2] = state.invert ? 255 - b : b;
              out[p + 3] = 255;
            }
          }
        }
      } else {
        const idx = Math.min(state.visitIdx, ts.frames_by_visit.length - 1);
        let baseGrid;
        if (state.mode === "stack") {
          baseGrid = state.followMotion && ts.frames_by_visit.length >= 2
            ? computeFollowMotionStack(payload, ts)
            : ts.stack;
        } else {
          baseGrid = state.followMotion
            ? shiftGrid(ts.frames_by_visit[idx], ...getVisitShiftPx(payload, ts, idx))
            : ts.frames_by_visit[idx];
        }
        const grid = injectTestSourceGrid(baseGrid);
        const [lo, hi] = percentileRange(grid);
        for (let y = 0; y < ny; y++) {
          for (let x = 0; x < nx; x++) {
            const p = (y * nx + x) * 4;
            const v = readGridCell(grid, y, x);
            if (!isFiniteNumber(v)) {
              out[p] = 55; out[p + 1] = 18; out[p + 2] = 28; out[p + 3] = 255;
            } else {
              const [r, g, b] = heatColor(scaleFlux(v, lo, hi, state.stretch), state.invert);
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
        ? (state.followMotion ? "Median stack (Follow motion)" : "Mean Stack")
        : state.mode === "coldiff"
          ? (coldiffMissing ? "Loading D6 and D4" : "Colour difference (D6 and D4)")
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

    if (state.injectTestSource && hasValidFrames(ts)) {
      const tx = w * 0.72;
      const ty = h * 0.28;
      ctx.strokeStyle = "#34d399";
      ctx.lineWidth = 1.5;
      if (ctx.setLineDash) ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.arc(tx, ty, 12, 0, Math.PI * 2);
      ctx.stroke();
      if (ctx.setLineDash) ctx.setLineDash([]);
      ctx.fillStyle = "#34d399";
      ctx.font = "11px monospace";
      ctx.fillText("Test S/N 5", Math.min(w - 75, tx + 14), Math.max(14, ty + 4));
    }

    if (Array.isArray(payload.sso_track) && payload.sso_track.length > 0) {
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 2;
      ctx.beginPath();
      let started = false;
      payload.sso_track.forEach((pt, idx) => {
        const [px, py] = projectSky(pt.ra_deg, pt.dec_deg);
        if (!started) {
          ctx.moveTo(px, py);
          started = true;
        } else {
          ctx.lineTo(px, py);
        }
        if (idx === 0 || idx === payload.sso_track.length - 1 || idx % Math.max(1, Math.floor(payload.sso_track.length / 8)) === 0) {
          ctx.fillStyle = "#f59e0b";
          ctx.fillRect(px - 2.5, py - 2.5, 5, 5);
        }
      });
      ctx.stroke();
      const firstPt = payload.sso_track[0];
      const lastPt = payload.sso_track[payload.sso_track.length - 1];
      const [fx, fy] = projectSky(firstPt.ra_deg, firstPt.dec_deg);
      const [lx, ly] = projectSky(lastPt.ra_deg, lastPt.dec_deg);
      ctx.fillStyle = "#f59e0b";
      ctx.font = "11px monospace";
      ctx.fillText(`MJD ${Number(firstPt.mjd).toFixed(0)}`, Math.max(4, Math.min(w - 72, fx + 6)), Math.max(12, Math.min(h - 6, fy - 4)));
      if (payload.sso_track.length > 1) {
        ctx.fillText(`MJD ${Number(lastPt.mjd).toFixed(0)}`, Math.max(4, Math.min(w - 72, lx + 6)), Math.max(24, Math.min(h - 6, ly + 12)));
      }
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
    const pts = frames.filter((f) => Number.isFinite(f.t_min) && (Number.isFinite(f.em_min) || state.payload.sso_track));
    if (pts.length === 0) {
      state.matrixMeta = null;
      ctx.fillStyle = "#93a4bd";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("No SPHEREx observation metadata rows matched this sky query.", 16, 40);
      return;
    }
    const ts = state.payload && state.payload.patch_timeseries;
    const visitMjds = (ts && Array.isArray(ts.visits))
      ? ts.visits.map((v) => v.mjd).filter((m) => isFiniteNumber(m))
      : [];
    const allMjds = pts.map((p) => p.t_min).concat(visitMjds);
    const minT = Math.min(...allMjds);
    const maxT = Math.max(...allMjds);
    const spanT = Math.max(maxT - minT, 1.0);
    const padL = 42;
    const padR = 16;
    const padT = 16;
    const padB = 24;
    state.matrixMeta = { minT, maxT, spanT, padL, padR, width: w };

    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, w - padL - padR, h - padT - padB);
    ctx.fillStyle = "#93a4bd";
    ctx.font = "11px monospace";
    ctx.fillText("5.0um", 4, padT + 10);
    ctx.fillText("0.75", 4, h - padB);
    ctx.fillText(`MJD ${minT.toFixed(0)}`, padL, h - 6);
    ctx.fillText(`MJD ${maxT.toFixed(0)}`, w - padR - 70, h - 6);

    pts.forEach((p) => {
      const rawEm = Number.isFinite(p.em_min) ? p.em_min : 3.5;
      const wlUm = rawEm > 1e-4 ? rawEm : rawEm * 1e6;
      const wl = Math.max(0.7, Math.min(5.1, wlUm > 20 ? wlUm / 1e6 : wlUm));
      const x = padL + ((p.t_min - minT) / spanT) * (w - padL - padR);
      const y = h - padB - ((wl - 0.7) / 4.4) * (h - padT - padB);
      ctx.fillStyle = p.obs_collection && p.obs_collection.includes("qr3") ? "#f59e0b" : "#38bdf8";
      ctx.fillRect(x - 2, y - 2, 4, 4);
    });

    if (visitMjds.length > 0 && ts.visits[state.visitIdx] && Number.isFinite(ts.visits[state.visitIdx].mjd)) {
      const vMjd = ts.visits[state.visitIdx].mjd;
      const vx = Math.max(padL, Math.min(w - padR, padL + ((vMjd - minT) / spanT) * (w - padL - padR)));
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(vx, padT);
      ctx.lineTo(vx, h - padB);
      ctx.stroke();
      ctx.fillStyle = "#f59e0b";
      ctx.font = "11px monospace";
      ctx.fillText(ts.visits[state.visitIdx].visit_id || `V${state.visitIdx + 1}`, Math.min(w - padR - 24, vx + 3), padT + 12);
    }
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
      const nov = classification.novelty ? classification.novelty.status : "not measured";
      const confProb = Number(ad.confidence);
      const confText = Number.isFinite(confProb) ? `${(confProb * 100).toFixed(0)}%` : "not measured";
      const labelWord = confidenceWord(confProb);
      const originText = classification.model_origin || "local";
      appendMoleculeMessage(
        "Model Estimate",
        `${labelWord}: ${ad.top_class}, ${confText}, novelty ${nov}, origin ${originText}, Estimated classifier output`,
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
    const warnMsg = data.warnings && data.warnings.length ? ` | Warning: ${data.warnings.join(". ")}` : "";
    setStatus(
      `${matchMsg} | RA ${data.query.ra_deg.toFixed(5)}°, Dec ${data.query.dec_deg.toFixed(5)}° | `
        + `${data.frames.length} SPHEREx frames | ${data.gaia_sources.length} Gaia DR3 stars${warnMsg}`,
      false
    );
    drawSkyCanvas();
    drawMatrixCanvas();
    renderFramesTable();
    renderExternalLinks();
    await drawSpectrumAndMolecules(seq, signal);
    if (els.motionSummary || els.lightcurveCanvas) {
      await loadTierAMetrics(seq, signal);
    }
  }

  function renderExternalLinks() {
    if (!els.externalLinks || !state.payload || !state.payload.query) return;
    els.externalLinks.replaceChildren();
    const links = buildExternalTelescopeLinks(state.payload.query.ra_deg, state.payload.query.dec_deg);
    if (!links.length) return;
    const lbl = document.createElement("span");
    lbl.className = "presets-label";
    lbl.textContent = "Other telescopes";
    els.externalLinks.appendChild(lbl);
    links.forEach((item) => {
      const a = document.createElement("a");
      a.href = item.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = item.label;
      els.externalLinks.appendChild(a);
    });
  }

  function drawLightCurveCanvas() {
    if (!els.lightcurveCanvas) return;
    const canvas = els.lightcurveCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    const metrics = state.tierAMetrics;
    const detInfo = metrics && metrics.per_detector && metrics.per_detector[state.detector];
    const visits = (detInfo && detInfo.visits) || [];
    const pts = visits.filter((v) => isFiniteNumber(v.mjd) && isFiniteNumber(v.flux_rel));
    if (!pts.length) {
      ctx.fillStyle = "#93a4bd";
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText("Light Curve not measured for current coordinate or detector.", 16, 40);
      return;
    }

    const padL = 48;
    const padR = 18;
    const padT = 18;
    const padB = 24;
    const minT = Math.min(...pts.map((p) => p.mjd));
    const maxT = Math.max(...pts.map((p) => p.mjd));
    const spanT = Math.max(maxT - minT, 1.0);
    const vals = pts.map((p) => p.flux_rel);
    const minF = Math.min(...vals);
    const maxF = Math.max(...vals);
    const padF = Math.max((maxF - minF) * 0.2, 1.0);
    const loF = minF - padF;
    const spanF = Math.max((maxF + padF) - loF, 1e-3);

    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, w - padL - padR, h - padT - padB);
    ctx.fillStyle = "#93a4bd";
    ctx.font = "11px monospace";
    ctx.fillText(`MJD ${minT.toFixed(0)}`, padL, h - 6);
    ctx.fillText(`MJD ${maxT.toFixed(0)}`, w - padR - 68, h - 6);
    ctx.fillText(detInfo.detector || state.detector, 6, padT + 10);

    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    pts.forEach((pt, idx) => {
      const x = pts.length === 1 ? (padL + w - padR) / 2 : padL + ((pt.mjd - minT) / spanT) * (w - padL - padR);
      const y = h - padB - ((pt.flux_rel - loF) / spanF) * (h - padT - padB);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    pts.forEach((pt, idx) => {
      const x = pts.length === 1 ? (padL + w - padR) / 2 : padL + ((pt.mjd - minT) / spanT) * (w - padL - padR);
      const y = h - padB - ((pt.flux_rel - loF) / spanF) * (h - padT - padB);
      if (isFiniteNumber(pt.flux_err_rel) && pt.flux_err_rel > 0) {
        const dy = Math.min(28, (pt.flux_err_rel / spanF) * (h - padT - padB));
        ctx.strokeStyle = "#93a4bd";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, y - dy);
        ctx.lineTo(x, y + dy);
        ctx.stroke();
      }
      ctx.fillStyle = idx === state.visitIdx ? "#f59e0b" : "#34d399";
      ctx.beginPath();
      ctx.arc(x, y, idx === state.visitIdx ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function renderTierAMetrics(metrics) {
    state.tierAMetrics = metrics || null;
    drawLightCurveCanvas();
    if (els.motionSummary) {
      els.motionSummary.replaceChildren();
      if (!metrics || !metrics.motion) {
        els.motionSummary.textContent = "Motion and Change Spectrum not measured outside bundled targets.";
      } else {
        const mo = metrics.motion;
        const satText = metrics.saturated_detectors && metrics.saturated_detectors.length
          ? `Core saturated in ${metrics.saturated_detectors.join(", ")}`
          : "No core saturation detected";
        const motionText = mo.status === "MEASURED"
          ? `Motion (${mo.origin || "Measured"}): ${mo.measured_total_arcsec_yr}\"/yr vs catalogue ${mo.catalogue_total_arcsec_yr}\"/yr, residual ${mo.residual_arcsec_yr}\"/yr`
          : `Motion not measured: ${mo.reason || "insufficient signal"} (catalogue ${mo.catalogue_total_arcsec_yr}\"/yr)`;
        const line1 = document.createElement("div");
        line1.textContent = motionText;
        const line2 = document.createElement("div");
        line2.className = metrics.saturated_detectors && metrics.saturated_detectors.length ? "status-warn" : "status-ok";
        line2.textContent = `${satText}, Gaia alignment RMS ${metrics.gaia_alignment_rms_arcsec ?? "not measured"}\"`;
        els.motionSummary.append(line1, line2);
      }
    }
    if (els.changeSpectrumList) {
      els.changeSpectrumList.replaceChildren();
      if (metrics && metrics.per_detector) {
        DETECTORS.forEach((detId) => {
          const info = metrics.per_detector[detId];
          if (!info) return;
          const card = document.createElement("div");
          card.className = "mol-item";
          const n = document.createElement("div");
          n.className = "mol-name";
          n.textContent = `${detId} Change Spectrum`;
          const v = document.createElement("div");
          const chg = info.change_last_vs_first || {};
          v.className = chg.status === "MEASURED" ? "mol-val" : "mol-val mol-refused";
          v.textContent = chg.status === "MEASURED"
            ? `Ratio ${chg.ratio_last_vs_first} (${chg.delta_pct >= 0 ? "+" : ""}${chg.delta_pct}%), median S/N ${info.median_snr}`
            : (chg.reason || "Not measured");
          card.append(n, v);
          els.changeSpectrumList.appendChild(card);
        });
      }
    }
  }

  async function loadTierAMetrics(seq, signal) {
    const payload = state.payload;
    if (!payload) {
      renderTierAMetrics(null);
      return;
    }
    if (payload.offline_tier_a_metrics) {
      renderTierAMetrics(payload.offline_tier_a_metrics);
      return;
    }
    const tid = (payload.matched_target && payload.matched_target.target_id)
      || (payload.patch_timeseries && payload.patch_timeseries.target_id);
    if (!tid) {
      renderTierAMetrics(null);
      return;
    }
    try {
      const opts = signal ? { signal } : undefined;
      const resp = await fetch(`/api/patch/metrics?target_id=${encodeURIComponent(tid)}`, opts);
      if (seq !== state.querySeq) return;
      if (resp && resp.ok) {
        renderTierAMetrics(await resp.json());
        return;
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
    }
    renderTierAMetrics(null);
  }

  function renderProofSummary(proof) {
    if (!els.proofBody) return;
    els.proofBody.replaceChildren();
    if (!proof || !Array.isArray(proof.tier_a_targets)) {
      els.proofBody.textContent = "Proof summary not measured.";
      return;
    }
    state.proofSummary = proof;
    const ml = proof.ml_evaluation || {};
    const mlLine = document.createElement("p");
    mlLine.className = "proof-meta";
    mlLine.textContent = ml.status === "AVAILABLE"
      ? `ML release ${ml.release_status} (${ml.model_version}), total spectra ${ml.total_spectra}, gold recall ${ml.gold_min_recall}, ECE ${ml.gold_ece}, E2 accuracy ${ml.e2_only_accuracy}`
      : `ML evaluation: ${ml.reason || "not measured"} (${ml.release_status || "UNPUBLISHED"})`;
    els.proofBody.appendChild(mlLine);
    if (ml.status === "AVAILABLE" && (ml.ucd_subtype_evaluation || ml.input_ladder || ml.cross_extraction_ratio)) {
      const tierBParts = [];
      if (ml.conformal_coverage !== undefined && ml.conformal_coverage !== null) {
        tierBParts.push(`conformal coverage ${ml.conformal_coverage}`);
      }
      const ucdSub = ml.ucd_subtype_evaluation;
      if (ucdSub && ucdSub.count) {
        tierBParts.push(`UCD <=2 subtypes ${ucdSub.within_2_subtypes_frac} (MAD ${ucdSub.mad_subtypes}, n=${ucdSub.count})`);
      }
      const lad = ml.input_ladder;
      if (lad && lad.rung1_e0_molecules_only && lad.rung3_all_102_bands && lad.rung4_bands_plus_stage10_spectrum_alone) {
        tierBParts.push(
          `input ladder gold acc R1 ${lad.rung1_e0_molecules_only.test_gold_accuracy} -> R3 ${lad.rung3_all_102_bands.test_gold_accuracy} -> R4 ${lad.rung4_bands_plus_stage10_spectrum_alone.test_gold_accuracy}`
        );
      }
      const xext = ml.cross_extraction_ratio;
      if (xext && xext.matched_count) {
        tierBParts.push(`S3/SPIFF ratio dev ${xext.max_abs_deviation} (n=${xext.matched_count})`);
      }
      if (tierBParts.length) {
        const tierBLine = document.createElement("p");
        tierBLine.className = "proof-meta";
        tierBLine.textContent = `Tier-B checks: ${tierBParts.join(" | ")}`;
        els.proofBody.appendChild(tierBLine);
      }
    }

    const wrap = document.createElement("div");
    wrap.className = "table-scroll";
    const tbl = document.createElement("table");
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    ["Target", "Gaia RMS", "D6 S/N", "Motion", "Residual", "Note"].forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    const tb = document.createElement("tbody");
    proof.tier_a_targets.forEach((t) => {
      const tr = document.createElement("tr");
      const cells = [
        t.target_name || t.target_id,
        t.gaia_alignment_rms_arcsec !== null && t.gaia_alignment_rms_arcsec !== undefined ? `${t.gaia_alignment_rms_arcsec}\"` : "not measured",
        t.d6_median_snr !== null && t.d6_median_snr !== undefined ? String(t.d6_median_snr) : "not measured",
        t.motion_status === "MEASURED" ? `${t.measured_total_arcsec_yr}\"/yr` : "Not measured",
        t.residual_arcsec_yr !== null && t.residual_arcsec_yr !== undefined ? `${t.residual_arcsec_yr}\"/yr` : "not measured",
        t.note || "",
      ];
      cells.forEach((txt) => {
        const td = document.createElement("td");
        td.textContent = txt;
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    tbl.append(thead, tb);
    wrap.appendChild(tbl);
    els.proofBody.appendChild(wrap);

    if (Array.isArray(proof.next_items) && proof.next_items.length) {
      const nextH = document.createElement("p");
      nextH.className = "proof-meta";
      nextH.textContent = "Next";
      const ul = document.createElement("ul");
      ul.className = "proof-next";
      proof.next_items.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        ul.appendChild(li);
      });
      els.proofBody.append(nextH, ul);
    }
  }

  function renderRecoveryCurveCanvas(searched) {
    const canvas = els.recoveryCurveCanvas;
    if (!canvas || typeof canvas.getContext !== "function") return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width || 520;
    const h = canvas.height || 170;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    const fields = (searched && searched.fields) || {};
    const series = [
      { key: "rwaur", det: "D6", label: "RW Aur D6", color: "#38bdf8" },
      { key: "w1925", det: "D6", label: "W1925 D6", color: "#f59e0b" },
      { key: "rwaur", det: "D3", label: "RW Aur D3", color: "#4ade80" },
      { key: "w1925", det: "D3", label: "W1925 D3", color: "#f472b6" },
    ].map((s) => {
      const mcs = (((fields[s.key] || {}).detectors || {})[s.det] || {}).motion_curves || [];
      return { ...s, curve: (mcs[0] && mcs[0].curve) || [] };
    }).filter((s) => s.curve.length > 0);

    if (!series.length) {
      ctx.fillStyle = "#93a4bd";
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText("Searched depth injection curves not loaded.", 16, 36);
      return;
    }

    const padL = 42, padR = 14, padT = 18, padB = 26;
    const cw = w - padL - padR;
    const ch = h - padT - padB;
    const mags = series.flatMap((s) => s.curve.map((r) => Number(r.ab_mag))).filter(isFiniteNumber);
    const minM = Math.min(...mags);
    const maxM = Math.max(...mags, minM + 1.0);

    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, cw, ch);
    [0.9, 0.5].forEach((ref) => {
      const yy = padT + (1.0 - ref) * ch;
      ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
      if (typeof ctx.setLineDash === "function") ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padL, yy);
      ctx.lineTo(w - padR, yy);
      ctx.stroke();
    });
    if (typeof ctx.setLineDash === "function") ctx.setLineDash([]);

    series.forEach((s, idx) => {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      s.curve.forEach((pt, i) => {
        const px = padL + ((Number(pt.ab_mag) - minM) / (maxM - minM)) * cw;
        const py = padT + (1.0 - Math.max(0, Math.min(1, Number(pt.recovery_rate) || 0))) * ch;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();
      ctx.fillStyle = s.color;
      ctx.font = "10px monospace";
      ctx.fillText(s.label, padL + 8 + idx * 92, padT - 4);
    });

    ctx.fillStyle = "#93a4bd";
    ctx.font = "10px monospace";
    ctx.fillText(`${minM.toFixed(1)} AB`, padL, h - 8);
    ctx.fillText(`${maxM.toFixed(1)} AB`, w - padR - 46, h - 8);
    ctx.fillText("90%", 8, padT + 0.1 * ch + 4);
    ctx.fillText("50%", 8, padT + 0.5 * ch + 4);
  }

  function renderProofV2(report) {
    if (!els.proofV2Extra) return;
    if (!report || !Array.isArray(report.tier_b_tests)) {
      els.proofV2Extra.hidden = true;
      return;
    }
    state.proofReportV2 = report;
    els.proofV2Extra.hidden = false;

    if (els.proofReportCardWrap) {
      els.proofReportCardWrap.replaceChildren();
      const cnt = report.counts || {};
      const hdr = document.createElement("p");
      hdr.className = "proof-meta";
      hdr.textContent = `Tier B Report Card (${report.pipeline_version || "pipeline"}): ${cnt.pass ?? 0} PASS · ${cnt.fail ?? 0} FAIL · ${cnt.not_measured ?? 0} NOT_MEASURED (honest thresholds, unedited)`;
      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      const tbl = document.createElement("table");
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");
      ["Test", "Target", "Pass mark", "Measured", "Status"].forEach((col) => {
        const th = document.createElement("th");
        th.textContent = col;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      const tb = document.createElement("tbody");
      report.tier_b_tests.forEach((b) => {
        const tr = document.createElement("tr");
        [b.test_id, b.target, b.pass_mark, b.measured, b.status].forEach((val, idx) => {
          const td = document.createElement("td");
          if (idx === 4) {
            const cls = val === "PASS" ? "pill-ok" : val === "FAIL" ? "pill-fail" : "pill-warn";
            td.appendChild(makePill(String(val || "NOT_MEASURED"), cls));
          } else {
            td.textContent = String(val ?? "");
          }
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
      tbl.append(thead, tb);
      wrap.appendChild(tbl);
      els.proofReportCardWrap.append(hdr, wrap);
    }

    if (report.searched_depth) {
      state.searchedDepth = report.searched_depth;
      renderRecoveryCurveCanvas(report.searched_depth);
      if (els.proofPlanetXStatement) {
        els.proofPlanetXStatement.textContent = report.searched_depth.planet_x_statement || "";
      }
    }

    if (els.proofLadderWrap) {
      const b13 = report.tier_b_tests.find((t) => t.test_id === "B13");
      const lims = Array.isArray(report.stated_limits) ? report.stated_limits : [];
      els.proofLadderWrap.textContent = (b13 ? `Input Ladder (B13): ${b13.measured}. ` : "") + (lims[0] || "");
    }

    if (els.proofCreditsWrap) {
      const creds = Array.isArray(report.credits) ? report.credits : [];
      const fmtCreds = creds
        .map((c) => (typeof c === "string" ? c : c && c.name ? `${c.name}: ${c.detail || ""}` : ""))
        .filter(Boolean);
      els.proofCreditsWrap.textContent = fmtCreds.length ? `Credits: ${fmtCreds.join(" | ")}` : "";
    }
  }

  function effectiveCaseState(c) {
    return (c && state.caseOverrides[c.case_id]) || (c && c.state) || "Open signal";
  }

  function renderRetroMovers() {
    if (!els.retroSummary && !els.retroList) return;
    const sum = state.b7Summary || {};
    const movers = state.retroMovers || [];
    if (els.retroSummary) {
      els.retroSummary.textContent = movers.length
        ? `Prediction check (B7 held-out epoch): ${sum.held ?? 0}/${sum.movers_tested ?? movers.length} held (clean unsaturated ${sum.clean_unsaturated_held || "n/a"})`
        : "Prediction check: no movers available.";
    }
    if (els.retroList) {
      els.retroList.replaceChildren();
      movers.forEach((m) => {
        const row = document.createElement("div");
        row.className = "retro-row";
        const left = document.createElement("span");
        left.textContent = `${m.target_name || m.target_id} (${m.detector || "det"})`;
        const right = document.createElement("span");
        const predTxt = isFiniteNumber(m.pred_sep_arcsec) ? `pred ${m.pred_sep_arcsec}"` : "n/a";
        const stayTxt = isFiniteNumber(m.stay_sep_arcsec) ? `stay ${m.stay_sep_arcsec}"` : "n/a";
        right.textContent = `${m.status} · ${predTxt} vs 2s=${m.sigma_arcsec ? (m.sigma_arcsec * 2).toFixed(2) : "n/a"}" · ${stayTxt}`;
        row.append(left, right);
        els.retroList.appendChild(row);
      });
    }
  }

  function renderSelectedCaseDetail(c) {
    if (!els.caseDetailBox) return;
    if (!c) {
      els.caseDetailBox.hidden = true;
      return;
    }
    els.caseDetailBox.hidden = false;
    const dispState = effectiveCaseState(c);
    if (els.caseDetailTitle) {
      els.caseDetailTitle.textContent = `${c.case_id} · ${dispState} · Estimate: ${c.top_class || "Unclassified"}`;
    }
    if (els.caseDetailSummary) {
      const predTxt = c.prediction
        ? ` | Locked next-epoch prediction: (${c.prediction.predicted_ra_deg}, ${c.prediction.predicted_dec_deg})`
        : "";
      els.caseDetailSummary.textContent = `${c.kind} in ${c.field_id} · P(real)=${c.p_real} · S/N ${c.snr} · ${c.reason || ""}${predTxt}`;
    }
    if (els.caseDetailChecks) {
      els.caseDetailChecks.replaceChildren();
      (c.machine_checks || []).forEach((chk) => {
        const res = String(chk.result || "");
        const tone = res === "PASS" || res === "OK" || res === "PENDING" ? "pill-ok" : res === "FAIL" ? "pill-fail" : "pill-warn";
        els.caseDetailChecks.appendChild(makePill(`${chk.name}: ${res}`, tone));
      });
    }
  }

  function renderSignalsCases() {
    renderRetroMovers();
    if (!els.casesList) return;
    const allCases = state.fieldCases || [];
    const filtered = state.caseStateFilter === "all"
      ? allCases
      : allCases.filter((c) => effectiveCaseState(c) === state.caseStateFilter);
    if (els.casesCountBadge) {
      els.casesCountBadge.textContent = `${filtered.length} of ${allCases.length} cases`;
    }
    els.casesList.replaceChildren();
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "proof-meta";
      empty.textContent = "No cases match the selected disposition.";
      els.casesList.appendChild(empty);
      renderSelectedCaseDetail(null);
      return;
    }
    let selectedObj = filtered.find((c) => c.case_id === state.selectedCaseId) || filtered[0];
    state.selectedCaseId = selectedObj.case_id;
    filtered.slice(0, 60).forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "search-result-row";
      btn.classList.toggle("active", c.case_id === state.selectedCaseId);
      const left = document.createElement("span");
      left.textContent = `${c.source_id} · ${effectiveCaseState(c)} · ${c.kind}`;
      const right = document.createElement("span");
      right.textContent = `P=${c.p_real} · S/N ${c.snr}`;
      btn.append(left, right);
      btn.addEventListener("click", () => selectCaseRecord(c));
      els.casesList.appendChild(btn);
    });
    renderSelectedCaseDetail(selectedObj);
  }

  async function selectCaseRecord(c) {
    if (!c) return;
    state.selectedCaseId = c.case_id;
    renderSignalsCases();
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__ || {};
    const fsRows = (bundle.field_search && Array.isArray(bundle.field_search.results)) ? bundle.field_search.results : [];
    const hit = (state.searchResults || []).find((r) => r.field_id === c.field_id && r.source_id === c.source_id)
      || fsRows.find((r) => r.field_id === c.field_id && r.source_id === c.source_id)
      || c;
    await selectFieldSearchResult(hit);
  }

  async function loadFieldCases() {
    if (!els.casesList && !els.retroList) return;
    let payload = null;
    try {
      const resp = await fetch("/api/field/cases");
      if (resp && resp.ok) payload = await resp.json();
    } catch (_err) {
      // Offline static fallback
    }
    if (!payload) {
      const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
      payload = bundle && bundle.field_cases;
    }
    if (payload) {
      state.fieldCases = Array.isArray(payload.cases) ? payload.cases : [];
      state.retroMovers = Array.isArray(payload.retro_movers) ? payload.retro_movers : [];
      state.b7Summary = payload.b7_summary || null;
      renderSignalsCases();
    }
  }

  async function loadSearchedDepth() {
    if (!els.searchedDepthToggle && !els.proofV2Extra && !els.proofPlanetXStatement) return;
    let payload = null;
    try {
      const resp = await fetch("/api/field/searched");
      if (resp && resp.ok) payload = await resp.json();
    } catch (_err) {
      // Offline static fallback
    }
    if (!payload) {
      const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
      payload = bundle && bundle.searched_depth;
    }
    if (payload) {
      state.searchedDepth = payload;
      renderRecoveryCurveCanvas(payload);
      if (els.proofPlanetXStatement && !els.proofPlanetXStatement.textContent) {
        els.proofPlanetXStatement.textContent = payload.planet_x_statement || "";
      }
      if (state.activeFieldId) drawSkyCanvas();
    }
  }

  async function loadProofSummary() {
    if (!els.proofBody) return;
    let summaryDone = false;
    try {
      const resp = await fetch("/api/proof/summary");
      if (resp && resp.ok) {
        renderProofSummary(await resp.json());
        summaryDone = true;
      }
    } catch (_err) {
      // Fallback to static bundle when API is switched off
    }
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
    if (!summaryDone) {
      if (bundle && bundle.proof_summary) {
        renderProofSummary(bundle.proof_summary);
      } else {
        renderProofSummary(null);
      }
    }
    let repV2 = null;
    try {
      const resp2 = await fetch("/api/proof/report");
      if (resp2 && resp2.ok) repV2 = await resp2.json();
    } catch (_err) {
      // Offline fallback
    }
    if (!repV2 && bundle && bundle.proof_report) {
      repV2 = bundle.proof_report;
    }
    if (repV2) renderProofV2(repV2);
  }

  async function loadSsoObject(rawName) {
    const cleanName = (rawName || "").trim();
    if (!cleanName) {
      if (els.ssoStatus) els.ssoStatus.textContent = "Enter a moving object name.";
      return;
    }
    const seq = ++state.querySeq;
    if (els.ssoStatus) els.ssoStatus.textContent = `Searching ${cleanName}`;
    setStatus(`Querying moving object ${cleanName}`, false);
    try {
      const resp = await fetch(`/api/sso?name=${encodeURIComponent(cleanName)}`);
      if (seq !== state.querySeq) return;
      if (!resp.ok) {
        let msg = `Moving object lookup returned HTTP ${resp.status}`;
        try {
          const err = await resp.json();
          if (err && err.detail) msg = err.detail;
        } catch (_e) {}
        if (els.ssoStatus) els.ssoStatus.textContent = msg;
        setStatus(msg, true);
        return;
      }
      const sso = await resp.json();
      if (seq !== state.querySeq) return;
      const mappedFrames = (sso.frames || []).map((fr) => ({
        obs_collection: sso.query_mode || "irsa_most",
        obs_id: fr.obs_id || "",
        energy_bandpassname: fr.detector || "SPHEREx",
        t_min: fr.mjd,
        em_min: fr.em_min_um !== null && fr.em_min_um !== undefined ? fr.em_min_um : 3.5,
        s_ra: fr.ra_deg,
        s_dec: fr.dec_deg,
        access_url: fr.uri || null,
      }));
      const trackPayload = {
        query: {
          coord_input: sso.object_name,
          ra_deg: sso.center_ra_deg ?? 0.0,
          dec_deg: sso.center_dec_deg ?? 0.0,
          fov_arcmin: 30.0,
          epoch_yr: state.epochYr,
          detector: state.detector,
        },
        source_mode: sso.query_mode || "irsa_most_spherex",
        matched_target: null,
        patch_timeseries: null,
        frames: mappedFrames,
        total_matching_frames: sso.total_frames,
        gaia_sources: [],
        spectrum_102: null,
        sso_track: sso.track_points || [],
        warnings: sso.total_frames ? [] : ["No SPHEREx frames matched moving object ephemeris"],
      };
      const rateMsg = isFiniteNumber(sso.estimated_rate_arcsec_hr) ? `, rate ${sso.estimated_rate_arcsec_hr}\"/hr` : "";
      if (els.ssoStatus) {
        els.ssoStatus.textContent = `${sso.object_name}: ${sso.total_frames} frames${rateMsg}`;
      }
      await applySkyPayload(trackPayload, seq, undefined);
    } catch (_err) {
      const msg = "IRSA moving object archive unreachable";
      if (els.ssoStatus) els.ssoStatus.textContent = msg;
      setStatus(msg, true);
    }
  }

  function triggerDownload(href, filename) {
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    if (document.body && typeof document.body.appendChild === "function") {
      document.body.appendChild(a);
    }
    if (typeof a.click === "function") a.click();
    if (typeof a.remove === "function") a.remove();
  }

  function exportPng() {
    if (!els.skyCanvas || typeof els.skyCanvas.toDataURL !== "function") return;
    const url = els.skyCanvas.toDataURL("image/png");
    triggerDownload(url, "phantom-worlds-view.png");
    setStatus("Exported PNG view.", false);
  }

  function exportCsv() {
    if (!state.payload) return;
    const lines = ["section,key,value,unit_or_note"];
    const q = state.payload.query || {};
    lines.push([csvCell("query"), csvCell("coord"), csvCell(q.coord_input || state.coord), csvCell("input")].join(","));
    lines.push([csvCell("query"), csvCell("ra_deg"), csvCell(q.ra_deg), csvCell("deg")].join(","));
    lines.push([csvCell("query"), csvCell("dec_deg"), csvCell(q.dec_deg), csvCell("deg")].join(","));
    if (state.tierAMetrics && state.tierAMetrics.motion) {
      const mo = state.tierAMetrics.motion;
      lines.push([csvCell("motion"), csvCell("status"), csvCell(mo.status), csvCell(mo.reason || "")].join(","));
      lines.push([csvCell("motion"), csvCell("measured_arcsec_yr"), csvCell(mo.measured_total_arcsec_yr ?? "not measured"), csvCell("arcsec/yr")].join(","));
      lines.push([csvCell("motion"), csvCell("catalogue_arcsec_yr"), csvCell(mo.catalogue_total_arcsec_yr ?? "not measured"), csvCell("arcsec/yr")].join(","));
    }
    if (state.tierAMetrics && state.tierAMetrics.per_detector) {
      DETECTORS.forEach((d) => {
        const chg = state.tierAMetrics.per_detector[d] && state.tierAMetrics.per_detector[d].change_last_vs_first;
        if (chg) {
          lines.push([csvCell("change_spectrum"), csvCell(d), csvCell(chg.ratio_last_vs_first ?? "not measured"), csvCell(chg.reason || `${chg.delta_pct}%`)].join(","));
        }
      });
    }
    (state.payload.frames || []).slice(0, 120).forEach((fr) => {
      lines.push([csvCell("frame"), csvCell(fr.obs_id), csvCell(fr.t_min), csvCell(fr.energy_bandpassname || "")].join(","));
    });
    const uri = `data:text/csv;charset=utf-8,${encodeURIComponent(lines.join("\n"))}`;
    triggerDownload(uri, "phantom-worlds-metrics.csv");
    setStatus("Exported CSV data.", false);
  }

  function matchesOfflineCategory(rec, catId) {
    const estAll = rec.estimate_all_data || {};
    const estSpec = rec.estimate_spectrum_alone || {};
    const names = new Set([estAll.top_class || "", estSpec.top_class || "", estSpec.template_class || "", estSpec.tree_class || ""]);
    (estAll.conformal_set || []).forEach((c) => names.add(c));
    (estSpec.conformal_set || []).forEach((c) => names.add(c));
    const mols = rec.molecules || {};
    if (catId === "ultracool_dwarf") return names.has("Ultracool dwarf");
    if (catId === "yso") return names.has("Young star with ice or dust");
    if (catId === "star") return names.has("Star");
    if (catId === "evolved_giant") return names.has("Evolved giant star");
    if (catId === "galaxy") return names.has("Galaxy");
    if (catId === "agn_quasar") return names.has("Active galaxy or quasar");
    if (catId === "moving_source") return rec.detector_hit === "mover" || rec.kind === "Moving candidate";
    if (catId === "variable_source") return Boolean(rec.is_variable);
    if (catId === "water_ice" || catId === "co2_ice" || catId === "co_ice") {
      const feats = (mols && mols.features) || {};
      const kMap = { water_ice: "H2O_ice_3_05", co2_ice: "CO2_4_26", co_ice: "CO_4_67" };
      const m = feats[kMap[catId]] || {};
      return m.status === "MEASURED" && isFiniteNumber(m.integrated_tau) && m.integrated_tau >= 0.1;
    }
    if (catId === "methane_dip") {
      const ch4 = ((mols && mols.features) || {}).CH4_3_3 || {};
      if (ch4.status !== "MEASURED" || !isFiniteNumber(ch4.integrated_tau) || ch4.integrated_tau < 30.0) {
        return false;
      }
      if (isFiniteNumber(ch4.p16) && isFiniteNumber(ch4.p84)) {
        const err = Math.max(Math.abs(ch4.p84 - ch4.p16) * 0.5, 1e-6);
        return ch4.integrated_tau / err >= 3.0;
      }
      return true;
    }
    return true;
  }

  function filterOfflineFieldSearch() {
    const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
    const fs = bundle && bundle.field_search;
    if (!fs || !Array.isArray(fs.results)) return null;
    if (fs.model_card) state.lastModelCard = fs.model_card;
    const rows = fs.results.filter((r) => {
      if (state.searchFieldScope !== "all" && r.field_id !== state.searchFieldScope) return false;
      if ((r.snr || 0) < state.searchMinSnr) return false;
      if ((r.blend_share || 0) > state.searchMaxBlend) return false;
      if (state.searchOnlyUnexplained && (r.unexplained_score || 0) < 0.45) return false;
      if (state.searchCategories.length && !state.searchCategories.some((c) => matchesOfflineCategory(r, c))) return false;
      return true;
    });
    rows.sort((a, b) => {
      if (state.searchSortBy === "snr") return (b.snr || 0) - (a.snr || 0);
      if (state.searchSortBy === "weirdness") {
        return ((b.novelty && b.novelty.weirdness_score) || 0) - ((a.novelty && a.novelty.weirdness_score) || 0);
      }
      return (b.priority || 0) - (a.priority || 0);
    });
    return {
      coverage_statement: fs.coverage_statement,
      total_matched: rows.length,
      results: rows.slice(0, 80),
    };
  }

  function makePill(text, toneClass) {
    const span = document.createElement("span");
    span.className = `pill ${toneClass || ""}`.trim();
    span.textContent = text;
    return span;
  }

  function renderIdentityStripCanvas(rec) {
    if (!els.identityStripCanvas) return;
    const canvas = els.identityStripCanvas;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#04070e";
    ctx.fillRect(0, 0, w, h);

    const padL = 42;
    const padR = 16;
    const padT = 16;
    const padB = 24;
    const pw = Math.max(10, w - padL - padR);
    const ph = Math.max(10, h - padT - padB);
    const toX = (wl) => padL + ((wl - 0.75) / (5.0 - 0.75)) * pw;

    // SPHEREx 0.75..5.0 um rainbow backdrop band
    const bandColors = ["#6366f1", "#38bdf8", "#34d399", "#facc15", "#fb923c", "#f87171"];
    DETECTORS.forEach((_d, i) => {
      const bx0 = padL + (i / DETECTORS.length) * pw;
      const bw = pw / DETECTORS.length;
      ctx.fillStyle = bandColors[i];
      ctx.fillRect(bx0, padT, bw, 4);
    });
    ctx.strokeStyle = "#26344d";
    ctx.strokeRect(padL, padT, pw, ph);
    ctx.fillStyle = "#93a4bd";
    ctx.font = "11px monospace";
    ctx.fillText("0.75 um", padL, h - 6);
    ctx.fillText("5.0 um", w - padR - 46, h - 6);

    const top3 = rec.top_3_classes || [];
    const meas6 = rec.measured_6band || [];
    const measMean = meas6.length
      ? meas6.reduce((acc, m) => acc + Math.max(m.flux_uJy || 0, 0), 0) / Math.max(meas6.length, 1)
      : 1.0;

    // Collect normalized curve values to auto-scale cleanly
    const allY = [];
    meas6.forEach((m) => { if (isFiniteNumber(m.flux_uJy) && m.flux_uJy > 0) allY.push(m.flux_uJy / Math.max(measMean, 1e-6)); });
    top3.slice(0, 3).forEach((t) => {
      (t.strip_norm_flux || []).forEach((v) => { if (isFiniteNumber(v) && v > 0) allY.push(v); });
    });
    const maxY = allY.length ? Math.max(...allY, 1.2) : 2.0;
    const toY = (nv) => padT + ph - (Math.max(0, Math.min(maxY, nv)) / maxY) * (ph - 10);

    const stripPalette = ["#38bdf8", "#a78bfa", "#64748b"];
    top3.slice(0, 3).forEach((t, idx) => {
      const wls = t.strip_wavelength_um || [];
      const fls = t.strip_norm_flux || [];
      if (!wls.length || wls.length !== fls.length) return;
      ctx.strokeStyle = stripPalette[idx] || "#64748b";
      ctx.lineWidth = idx === 0 ? 1.8 : 1.0;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < wls.length; i++) {
        if (!isFiniteNumber(wls[i]) || !isFiniteNumber(fls[i])) continue;
        const x = toX(wls[i]);
        const y = toY(fls[i]);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });

    meas6.forEach((m) => {
      if (!isFiniteNumber(m.wavelength_um) || !isFiniteNumber(m.flux_uJy)) return;
      const x = toX(m.wavelength_um);
      const y = toY(m.flux_uJy / Math.max(measMean, 1e-6));
      ctx.fillStyle = "#f59e0b";
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function renderModelCardModal() {
    if (!els.modelCardBody) return;
    els.modelCardBody.replaceChildren();
    const mc = state.lastModelCard || ((globalThis.__PHANTOM_STATIC_FALLBACK__ && globalThis.__PHANTOM_STATIC_FALLBACK__.field_search) || {}).model_card;
    if (!mc) {
      els.modelCardBody.textContent = "Model provenance metadata unavailable.";
      return;
    }
    const g = mc.gold_high_snr || {};
    const m1 = mc.m1_calibration || {};
    const lines = [
      `Model version: ${mc.model_version || "unknown"} | Release gate status: ${mc.release_status || "UNPUBLISHED"}`,
      `Gold test set (W2<=14): count=${g.count ?? "not measured"}, min recall=${g.min_recall ?? "not measured"}, ECE=${g.ece ?? "not measured"}, conformal coverage=${g.conformal_coverage ?? "not measured"}`,
      `M1 artefact screen: P(real) >= ${m1.p_threshold_1pct_fpr ?? "not measured"}, val FPR=${m1.val_false_pass_rate ?? "not measured"}, B6 recall=${m1.b6_recall_at_1pct_fpr ?? m1.recall_at_1pct_fpr ?? "not measured"}`,
      "Honest limits: broad D1..D6 field stacks measure 6 detector averages (not full 102 LVF channels); model outputs are calibrated estimates, never confirmed truth.",
    ];
    lines.forEach((txt) => {
      const p = document.createElement("p");
      p.className = "proof-meta";
      p.textContent = txt;
      els.modelCardBody.appendChild(p);
    });
  }

  function renderIdentityV2(rec) {
    if (!els.identityCard) return;
    if (!rec) {
      els.identityCard.hidden = true;
      return;
    }
    els.identityCard.hidden = false;
    state.selectedFieldSource = rec;
    if (rec.model_card) state.lastModelCard = rec.model_card;
    if (els.identityTitle) els.identityTitle.textContent = `Identity v2 · ${rec.source_id}`;

    const estSpec = rec.estimate_spectrum_alone || {};
    const estAll = rec.estimate_all_data || {};
    if (els.identityHeader) {
      els.identityHeader.replaceChildren();
      const d1 = document.createElement("div");
      const confAll = isFiniteNumber(estAll.confidence) ? `${Math.round(estAll.confidence * 100)}%` : "n/a";
      const confSpec = isFiniteNumber(estSpec.confidence) ? `${Math.round(estSpec.confidence * 100)}%` : "n/a";
      d1.textContent = `${rec.kind} in ${rec.field_name} (${Number(rec.ra_deg).toFixed(5)}, ${Number(rec.dec_deg).toFixed(5)}) | Estimate all data: ${estAll.top_class || "Unclassified"} (${confAll}) | Spectrum alone: ${estSpec.top_class || "Unclassified"} (${confSpec})`;
      const d2 = document.createElement("div");
      d2.className = "status-warn";
      d2.textContent = rec.spectral_sampling || "6-band broadband stack; unmeasured channels marked explicitly.";
      els.identityHeader.append(d1, d2);
    }

    if (els.identityBands) {
      els.identityBands.replaceChildren();
      (rec.deciding_bands || []).forEach((b) => {
        const isM = b.status === "MEASURED";
        const label = isM ? `${b.detector} (${b.cwave_um}um): ${b.flux_uJy} uJy` : `${b.detector} (${b.cwave_um}um): UNMEASURED`;
        els.identityBands.appendChild(makePill(label, isM ? "pill-ok" : "pill-muted"));
      });
    }

    renderIdentityStripCanvas(rec);

    if (els.identityTop3) {
      els.identityTop3.replaceChildren();
      (rec.top_3_classes || []).forEach((t, idx) => {
        const card = document.createElement("div");
        card.className = "mol-item";
        const n = document.createElement("div");
        n.className = "mol-name";
        n.textContent = `#${idx + 1} Estimate: ${t.class_name}`;
        const v = document.createElement("div");
        v.className = "mol-val";
        v.textContent = `Score ${Math.round((t.score || 0) * 100)}% · chi2_red ${t.chi2_red ?? "n/a"}`;
        card.append(n, v);
        els.identityTop3.appendChild(card);
      });
    }

    if (els.identityChecks) {
      els.identityChecks.replaceChildren();
      const mc = rec.machine_checks || {};
      els.identityChecks.appendChild(makePill(`M1 P(real)=${rec.p_real}`, rec.m1_passed_1pct_fpr ? "pill-ok" : "pill-fail"));
      els.identityChecks.appendChild(makePill(`PSF shape: ${mc.psflike_shape ? "OK" : "FAIL"}`, mc.psflike_shape ? "pill-ok" : "pill-warn"));
      els.identityChecks.appendChild(makePill(`Multi-exp: ${mc.multi_exposure_repeat ? "OK" : "1x"}`, mc.multi_exposure_repeat ? "pill-ok" : "pill-warn"));
      els.identityChecks.appendChild(makePill(`Halo: ${mc.saturated_halo_clear ? "Clear" : "Flagged"}`, mc.saturated_halo_clear ? "pill-ok" : "pill-fail"));
      els.identityChecks.appendChild(makePill(`Xtalk/Ghost: ${mc.crosstalk_ghost_clear ? "Clear" : "Flagged"}`, mc.crosstalk_ghost_clear ? "pill-ok" : "pill-fail"));
      const ec = rec.edge_check || {};
      if (ec.status && ec.status !== "NOT_MEASURED") {
        els.identityChecks.appendChild(makePill(`Edge: ${ec.status}`, ec.flagged ? "pill-warn" : "pill-ok"));
      }
      (rec.crosstalk_ghost_reasons || []).forEach((rsn) => {
        els.identityChecks.appendChild(makePill(rsn, "pill-fail"));
      });
    }

    if (els.identityMeta) {
      els.identityMeta.replaceChildren();
      const mo = rec.motion_mas_yr || {};
      const mLine = document.createElement("div");
      const pmTxt = isFiniteNumber(mo.pmra_mas_yr) ? `pmRA ${mo.pmra_mas_yr}, pmDec ${mo.pmdec_mas_yr} mas/yr, plx ${mo.parallax_mas ?? "n/a"} mas` : (isFiniteNumber(mo.rate_arcsec_hr) ? `Track rate ${mo.rate_arcsec_hr} "/hr` : "No catalogue PM measured");
      mLine.textContent = `S/N ${rec.snr} | Blend share ${rec.blend_share} | Motion: ${pmTxt}`;
      const ep = rec.epochs || {};
      const epLine = document.createElement("div");
      const m2 = ep["2MASS_J2000"] || {};
      const w2 = ep.WISE_2015 || {};
      const g3 = ep.GaiaDR3_2016 || {};
      epLine.textContent = `Epochs: 2MASS Ks=${m2.ks_mag ?? "n/a"} · WISE W1=${w2.w1_mag ?? "n/a"} · Gaia G=${g3.g_mag ?? "n/a"} · SPHEREx ${(ep.SPHEREx_2025_2026 || []).length} visits`;
      const molLine = document.createElement("div");
      const molObj = rec.molecules || {};
      molLine.textContent = molObj.status === "REFUSED"
        ? `Molecules: ${molObj.refusal_reason || "Refused"}`
        : `Molecules: ${molObj.status || "Not measured"}`;
      els.identityMeta.append(mLine, epLine, molLine);
    }
    drawSkyCanvas();
  }

  async function selectFieldSearchResult(rec) {
    if (!rec) return;
    let detail = rec;
    try {
      const resp = await fetch(`/api/field/${encodeURIComponent(rec.field_id)}/source/${encodeURIComponent(rec.source_id)}`);
      if (resp && resp.ok) detail = await resp.json();
    } catch (_err) {
      // Keep offline record when API is unreachable
    }
    renderIdentityV2(detail);
    renderSearchResultsList();
    if (state.activeFieldId !== detail.field_id) {
      await loadFieldScene(detail.field_id, { preserveSelection: true });
    } else {
      drawSkyCanvas();
    }
  }

  function renderSearchResultsList() {
    if (!els.searchResultsList) return;
    els.searchResultsList.replaceChildren();
    if (els.searchMatchCount) els.searchMatchCount.textContent = `${state.searchResults.length} shown`;
    if (!state.searchResults.length) {
      const empty = document.createElement("div");
      empty.className = "proof-meta";
      empty.textContent = "No sources match the active Search-by-Light filters.";
      els.searchResultsList.appendChild(empty);
      return;
    }
    state.searchResults.forEach((rec) => {
      const btn = document.createElement("button");
      btn.type = "button";
      const isSel = state.selectedFieldSource && state.selectedFieldSource.source_id === rec.source_id && state.selectedFieldSource.field_id === rec.field_id;
      btn.className = `search-result-row${isSel ? " active" : ""}`;
      const clsTxt = (rec.estimate_all_data && rec.estimate_all_data.top_class) || rec.kind;
      const left = document.createElement("span");
      left.textContent = `${rec.source_id} · ${clsTxt}`;
      const right = document.createElement("span");
      right.textContent = `${rec.field_id.toUpperCase()} S/N ${rec.snr} · P=${rec.p_real}`;
      btn.append(left, right);
      btn.addEventListener("click", () => {
        selectFieldSearchResult(rec);
      });
      els.searchResultsList.appendChild(btn);
    });
  }

  async function loadFieldSearch() {
    if (!els.searchResultsList) return;
    let payload = null;
    try {
      const params = new URLSearchParams({
        field_id: state.searchFieldScope,
        categories: state.searchCategories.join(","),
        min_snr: String(state.searchMinSnr),
        max_blend: String(state.searchMaxBlend),
        only_unexplained: String(state.searchOnlyUnexplained),
        sort_by: state.searchSortBy,
        limit: "80",
      });
      const resp = await fetch(`/api/field/search?${params.toString()}`);
      if (resp && resp.ok) payload = await resp.json();
    } catch (_err) {
      // Offline fallback when API is stopped
    }
    if (!payload) payload = filterOfflineFieldSearch();
    if (!payload) return;
    if (els.searchCoverageNote && payload.coverage_statement) {
      els.searchCoverageNote.textContent = payload.coverage_statement;
    }
    state.searchResults = payload.results || [];
    if (els.searchMatchCount) {
      els.searchMatchCount.textContent = `${payload.total_matched ?? state.searchResults.length} matched`;
    }
    renderSearchResultsList();
  }

  async function loadFieldScene(fieldId, options) {
    const seq = ++state.querySeq;
    if (state.abortController) state.abortController.abort();
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    state.abortController = controller;
    const signal = controller ? controller.signal : undefined;

    state.activeFieldId = fieldId;
    if (!options || !options.preserveSelection) {
      state.selectedFieldSource = null;
      renderIdentityV2(null);
    }
    state.fieldFadeProgress = 1.0;
    state.fieldFadeFrom = state.fieldLayer;
    state.playing = false;
    setActiveButtons();
    setStatus(`Loading field "${fieldId}" (${state.detector})...`, false);

    let data = null;
    let sourceLabel = "tier_b_live_api";
    try {
      const params = new URLSearchParams({ detector: state.detector });
      const resp = await fetch(`/api/field/${encodeURIComponent(fieldId)}/remove_known?${params.toString()}`, signal ? { signal } : undefined);
      if (seq !== state.querySeq) return;
      if (resp && resp.ok) {
        data = await resp.json();
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
    }

    if (!data) {
      const bundle = globalThis.__PHANTOM_STATIC_FALLBACK__;
      const fbField = bundle && bundle.fields && bundle.fields[fieldId];
      const fbDet = fbField && fbField.remove_known && fbField.remove_known[state.detector];
      if (fbDet) {
        data = fbDet;
        sourceLabel = "hour0_static_fallback";
      }
    }
    if (seq !== state.querySeq) return;
    if (!data) {
      setStatus(`Field "${fieldId}" is unavailable (API offline and missing from static bundle).`, true);
      return;
    }

    state.fieldData = data;
    state.payload = {
      query: {
        coord_input: data.field_name,
        ra_deg: data.center_ra_deg,
        dec_deg: data.center_dec_deg,
        fov_arcmin: data.fov_arcmin || 6.56,
        detector: data.detector,
      },
      source_mode: sourceLabel,
    };
    if (els.coordInput) els.coordInput.value = `${data.center_ra_deg.toFixed(4)} ${data.center_dec_deg.toFixed(4)}`;
    if (els.modeBadge) els.modeBadge.textContent = sourceLabel;
    const wl = Array.isArray(data.wavelength_range_um) ? data.wavelength_range_um.join("–") : state.detector;
    const nCat = (data.catalogue_counts && data.catalogue_counts.merged_catalogue_stars) || (data.fitted_sources && data.fitted_sources.length) || 0;
    setStatus(
      `${data.field_name} (${data.plane_type}) | ${data.detector} [${wl} µm] | ${nCat} catalogued sources fitted | ${data.cutout_origin || "real_spherex_s3_wcs_cutout"}`,
      false
    );
    drawSkyCanvas();
    renderExternalLinks();
  }

  async function loadSkyQuery() {
    state.activeFieldId = null;
    state.fieldData = null;
    state.selectedFieldSource = null;
    renderIdentityV2(null);
    setActiveButtons();
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
        if (els.matrixCanvas && state.matrixMeta) drawMatrixCanvas();
        if (els.lightcurveCanvas && state.tierAMetrics) drawLightCurveCanvas();
      }
    }, state.speedMs);
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
      if (btn.dataset.field) {
        loadFieldScene(btn.dataset.field);
        return;
      }
      state.activeFieldId = null;
      state.fieldData = null;
      state.coord = btn.dataset.coord;
      els.coordInput.value = state.coord;
      syncInputsToState();
      loadSkyQuery();
    });
  });

  document.querySelectorAll(".rmknown-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      setFieldLayer(btn.dataset.layer);
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
    if (state.activeFieldId) {
      return loadFieldScene(state.activeFieldId);
    }
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
          drawLightCurveCanvas();
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
    if (state.activeFieldId && state.fieldData && Array.isArray(state.fieldData.image_stack)) {
      const fd = state.fieldData;
      const rect = els.skyCanvas.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0 || !isFiniteNumber(ev.clientX) || !isFiniteNumber(ev.clientY)) {
        return;
      }
      const ny = fd.image_stack.length;
      const nx = fd.image_stack[0].length;
      const px = Math.floor(((ev.clientX - rect.left) / rect.width) * nx);
      const py = Math.floor(((ev.clientY - rect.top) / rect.height) * ny);
      if (px >= 0 && px < nx && py >= 0 && py < ny) {
        const fmt = (v) => (isFiniteNumber(v) ? v.toFixed(3) : "NaN");
        const vImg = readGridCell(fd.image_stack, py, px);
        const vMod = readGridCell(fd.model_stack, py, px);
        const vRes = readGridCell(fd.residual_stack, py, px);
        if (els.pixelReadout) {
          els.pixelReadout.textContent = `Pixel (${px}, ${py}) | Image: ${fmt(vImg)} | Model: ${fmt(vMod)} | Residual: ${fmt(vRes)} MJy/sr`;
        }
      }
      return;
    }
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
      ? (state.followMotion && ts.frames_by_visit.length >= 2 ? computeFollowMotionStack(state.payload, ts) : ts.stack)
      : state.mode === "coldiff"
        ? (buildColourDiffGrid(state.payload) || ts.stack)
        : (state.mode === "difference" && ts.difference)
          ? ts.difference
          : ts.frames_by_visit[Math.min(state.visitIdx, ts.frames_by_visit.length - 1)];
    const val = readGridCell(grid, py, px);
    const valText = isFiniteNumber(val) ? `${val.toFixed(3)} rel` : "MASKED (NaN)";
    els.pixelReadout.textContent = `Pixel (${px}, ${py}) | Flux: ${valText} | Mask bits: ${maskVal}`;
  });

  if (els.speedSelect) {
    els.speedSelect.addEventListener("change", () => {
      const spd = Number(els.speedSelect.value);
      state.speedMs = [300, 750, 1200].includes(spd) ? spd : 750;
      syncUrlParams();
      startLoop();
    });
  }

  if (els.invertToggle) {
    els.invertToggle.addEventListener("change", () => {
      state.invert = els.invertToggle.checked;
      syncUrlParams();
      drawSkyCanvas();
    });
  }

  if (els.followMotionToggle) {
    els.followMotionToggle.addEventListener("change", () => {
      state.followMotion = els.followMotionToggle.checked;
      syncUrlParams();
      drawSkyCanvas();
    });
  }

  if (els.injectToggle) {
    els.injectToggle.addEventListener("change", () => {
      state.injectTestSource = els.injectToggle.checked;
      drawSkyCanvas();
    });
  }

  if (els.matrixCanvas) {
    els.matrixCanvas.addEventListener("click", (ev) => {
      const meta = state.matrixMeta;
      const ts = state.payload && state.payload.patch_timeseries;
      if (!meta || !ts || !Array.isArray(ts.visits) || !ts.visits.length) return;
      const rect = els.matrixCanvas.getBoundingClientRect();
      if (!rect || !isFiniteNumber(rect.width) || rect.width <= 0 || !isFiniteNumber(ev.clientX)) return;
      const canvasX = ((ev.clientX - rect.left) / rect.width) * meta.width;
      const frac = Math.max(0, Math.min(1, (canvasX - meta.padL) / Math.max(1, meta.width - meta.padL - meta.padR)));
      const clickedMjd = meta.minT + frac * meta.spanT;
      let bestIdx = 0;
      let bestDiff = Infinity;
      ts.visits.forEach((v, i) => {
        if (isFiniteNumber(v.mjd)) {
          const d = Math.abs(v.mjd - clickedMjd);
          if (d < bestDiff) {
            bestDiff = d;
            bestIdx = i;
          }
        }
      });
      state.playing = false;
      state.mode = "play";
      state.visitIdx = bestIdx;
      els.scrubber.value = String(bestIdx);
      setActiveButtons();
      syncUrlParams();
      drawSkyCanvas();
      drawMatrixCanvas();
      drawLightCurveCanvas();
    });
  }

  if (els.ssoQueryBtn && els.ssoInput) {
    els.ssoQueryBtn.addEventListener("click", () => {
      loadSsoObject(els.ssoInput.value);
    });
  }

  document.querySelectorAll(".sso-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.sso || "";
      if (els.ssoInput) els.ssoInput.value = target;
      loadSsoObject(target);
    });
  });

  if (els.exportPngBtn) {
    els.exportPngBtn.addEventListener("click", exportPng);
  }

  if (els.exportCsvBtn) {
    els.exportCsvBtn.addEventListener("click", exportCsv);
  }

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

  document.querySelectorAll(".search-cat-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const c = btn.dataset.cat;
      if (!c) return;
      const idx = state.searchCategories.indexOf(c);
      if (idx >= 0) {
        state.searchCategories.splice(idx, 1);
        btn.classList.toggle("active", false);
        btn.setAttribute("aria-pressed", "false");
      } else {
        state.searchCategories.push(c);
        btn.classList.toggle("active", true);
        btn.setAttribute("aria-pressed", "true");
      }
      loadFieldSearch();
    });
  });

  if (els.searchFieldScope) {
    els.searchFieldScope.addEventListener("change", () => {
      state.searchFieldScope = els.searchFieldScope.value;
      loadFieldSearch();
    });
  }
  if (els.searchMinSnr) {
    els.searchMinSnr.addEventListener("input", () => {
      state.searchMinSnr = Number(els.searchMinSnr.value) || 0;
      if (els.searchMinSnrVal) els.searchMinSnrVal.textContent = String(state.searchMinSnr);
      loadFieldSearch();
    });
  }
  if (els.searchMaxBlend) {
    els.searchMaxBlend.addEventListener("input", () => {
      state.searchMaxBlend = Number(els.searchMaxBlend.value) || 1.0;
      if (els.searchMaxBlendVal) els.searchMaxBlendVal.textContent = state.searchMaxBlend.toFixed(2);
      loadFieldSearch();
    });
  }
  if (els.searchUnexplainedOnly) {
    els.searchUnexplainedOnly.addEventListener("change", () => {
      state.searchOnlyUnexplained = Boolean(els.searchUnexplainedOnly.checked);
      loadFieldSearch();
    });
  }
  if (els.searchSortSelect) {
    els.searchSortSelect.addEventListener("change", () => {
      state.searchSortBy = els.searchSortSelect.value || "priority";
      loadFieldSearch();
    });
  }
  if (els.modelCardOpenBtn && els.modelCardModal) {
    els.modelCardOpenBtn.addEventListener("click", () => {
      renderModelCardModal();
      els.modelCardModal.hidden = false;
    });
  }
  if (els.modelCardCloseBtn && els.modelCardModal) {
    els.modelCardCloseBtn.addEventListener("click", () => {
      els.modelCardModal.hidden = true;
    });
  }
  if (typeof document.addEventListener === "function" && els.modelCardModal) {
    document.addEventListener("keydown", (ev) => {
      if (ev && ev.key === "Escape" && !els.modelCardModal.hidden) {
        els.modelCardModal.hidden = true;
      }
    });
  }

  if (els.searchedDepthToggle) {
    els.searchedDepthToggle.addEventListener("change", () => {
      state.showSearchedDepth = Boolean(els.searchedDepthToggle.checked);
      if (!state.searchedDepth) loadSearchedDepth();
      if (state.showSearchedDepth && !state.activeFieldId) {
        loadFieldScene("w1925");
      } else {
        drawSkyCanvas();
      }
    });
  }

  document.querySelectorAll(".case-state-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.caseStateFilter = btn.dataset.state || "all";
      document.querySelectorAll(".case-state-btn").forEach((b) => {
        const on = b === btn;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      renderSignalsCases();
    });
  });

  function applyLocalCaseTriage(newState) {
    if (!state.selectedCaseId) return;
    state.caseOverrides[state.selectedCaseId] = newState;
    renderSignalsCases();
  }
  if (els.caseFlagArtefactBtn) {
    els.caseFlagArtefactBtn.addEventListener("click", () => applyLocalCaseTriage("Artefact"));
  }
  if (els.caseMarkExplainedBtn) {
    els.caseMarkExplainedBtn.addEventListener("click", () => applyLocalCaseTriage("Explained by catalogue"));
  }
  if (els.caseReopenBtn) {
    els.caseReopenBtn.addEventListener("click", () => applyLocalCaseTriage("Open signal"));
  }

  applyUrlParams();
  setActiveButtons();
  startLoop();
  loadSkyQuery();
  if (els.proofBody) loadProofSummary();
  loadFieldSearch();
  loadFieldCases();
  loadSearchedDepth();
})();
