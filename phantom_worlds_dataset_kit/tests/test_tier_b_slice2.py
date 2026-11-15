"""Tests for Tier-B Slice 2: T44 Movers/Leftovers, T45 Identity v2, T45b Crosstalk/Ghost, M1, B3/B6/B10 & T51/T52 UI."""

import json
import os
import shutil
import subprocess
import unittest
import warnings

from fastapi.testclient import TestClient
import numpy as np

from phantom_worlds.api import create_app
from phantom_worlds.contracts import DEFAULT_CONTRACTS_DIR
from phantom_worlds.tier_b_detectors import (
    SEARCH_CATEGORY_FILTERS,
    analyze_field_candidates,
    evaluate_crosstalk_ghost_risk,
    evaluate_slice2_benchmarks,
    get_source_identity_v2,
    score_m1_candidate,
    search_field_sources,
    train_and_calibrate_m1_classifier,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATIC_DIR = os.path.join(REPO_ROOT, "phantom_worlds", "static")


class TestTierBSlice2Engine(unittest.TestCase):
    def test_crosstalk_ghost_and_tgt03_eps_indi_saturation_screen(self):
        # 1. Synthetic H2RG 64-px intra-channel mirrored crosstalk + quadrant reflection optical ghost
        mask_syn = np.zeros((64, 64), dtype=np.uint8)
        mask_syn[20, 20] = 2  # bright/saturated core
        anchors = [(20.0, 20.0, 120.0)]

        # Intra-channel mirror x = 64 - 20 = 44 at same row (y=20)
        cg_xtalk = evaluate_crosstalk_ghost_risk(44.0, 20.0, 1.2, mask_syn, anchors)
        self.assertFalse(cg_xtalk["crosstalk_ghost_clear"])
        self.assertTrue(any("crosstalk" in r for r in cg_xtalk["reasons"]))

        # Diagonal/quadrant optical ghost reflection (63-20=43, 63-20=43)
        cg_ghost = evaluate_crosstalk_ghost_risk(43.0, 43.0, 1.5, mask_syn, anchors)
        self.assertFalse(cg_ghost["crosstalk_ghost_clear"])
        self.assertTrue(any("optical ghost" in r for r in cg_ghost["reasons"]))

        # Clean isolated field position far from bright anchors & saturation
        cg_clean = evaluate_crosstalk_ghost_risk(8.0, 52.0, 8.0, mask_syn, anchors)
        self.assertTrue(cg_clean["saturated_halo_clear"])
        self.assertTrue(cg_clean["crosstalk_ghost_clear"])

        # 2. Real TGT-03 (Eps Indi) D4 saturation mask (bit 2 = OVERFLOW_SATURATED)
        mpath = os.path.join(DEFAULT_CONTRACTS_DIR, "targets", "TGT-03", "manifest.json")
        bpath = os.path.join(DEFAULT_CONTRACTS_DIR, "targets", "TGT-03", "mask.bin")
        with open(mpath, encoding="utf-8") as mf:
            manifest = json.load(mf)
        shape = tuple(manifest["pack_binary_layout"]["shape"])
        tgt3_mask = np.fromfile(bpath, dtype=np.uint8).reshape(shape)
        d4_mask = tgt3_mask[0, 3]
        sat_coords = np.argwhere((d4_mask & 2) != 0)
        self.assertGreater(len(sat_coords), 0, "Expected real bit-2 saturated pixels in TGT-03 D4")
        sy, sx = float(sat_coords[0][0]), float(sat_coords[0][1])

        cg_tgt3 = evaluate_crosstalk_ghost_risk(sx + 1.5, sy + 1.0, 2.0, d4_mask, [(sx, sy, 250.0)])
        self.assertFalse(cg_tgt3["saturated_halo_clear"])
        m1 = train_and_calibrate_m1_classifier(DEFAULT_CONTRACTS_DIR)
        p_real, passed = score_m1_candidate(
            m1,
            [12.0, 0.9, 0.35, 0.85, 1.1, 0.1, 2.0, 3.0, cg_tgt3["min_sat_or_bright_px"], cg_tgt3["spike_axis_score"], cg_tgt3["ghost_xtalk_score"], 15.0],
            {"saturated_halo_clear": cg_tgt3["saturated_halo_clear"], "crosstalk_ghost_clear": cg_tgt3["crosstalk_ghost_clear"], "mask_bit_clean": True},
        )
        self.assertLessEqual(p_real, 0.15)
        self.assertFalse(passed)

    def test_slice2_benchmarks_b3_b6_b10_zero_warnings(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            bench = evaluate_slice2_benchmarks(DEFAULT_CONTRACTS_DIR)
            all_nan_warns = [w for w in caught if "All-NaN slice" in str(w.message)]
            self.assertEqual(all_nan_warns, [], f"Unexpected All-NaN RuntimeWarnings: {all_nan_warns}")

        self.assertTrue(bench["B3"]["passed"], f"B3 mover recovery should be >=80%: {bench['B3']}")
        self.assertGreaterEqual(bench["B3"]["recovery_rate"], 0.80)

        self.assertLessEqual(bench["B6"]["val_false_pass_rate"], 0.01, f"B6 M1 FPR exceeded 1%: {bench['B6']}")
        self.assertGreaterEqual(bench["B6"]["recall_at_1pct_fpr"], 0.80)

        self.assertTrue(bench["B10"]["passed"], f"B10 steady edge flag rate exceeded 1%: {bench['B10']}")
        self.assertGreaterEqual(bench["B10"]["steady_count"], 15)


class TestTierBSlice2ApiAndUi(unittest.TestCase):
    def test_api_field_search_and_identity_v2_endpoints(self):
        app = create_app()
        client = TestClient(app)

        r_search = client.get("/api/field/search", params={"field_id": "all", "min_snr": 8, "limit": 25})
        self.assertEqual(r_search.status_code, 200)
        body = r_search.json()
        self.assertGreaterEqual(body["total_matched"], 10)
        self.assertEqual(len(body["categories_available"]), len(SEARCH_CATEGORY_FILTERS))
        self.assertIn("full-sky catalog search not active", body["coverage_statement"])

        first = body["results"][0]
        r_id = client.get(f"/api/field/{first['field_id']}/source/{first['source_id']}")
        self.assertEqual(r_id.status_code, 200)
        det = r_id.json()
        self.assertEqual(det["source_id"], first["source_id"])
        self.assertIn("machine_checks", det)
        self.assertIn("deciding_bands", det)
        self.assertIn("model_card", det)
        self.assertEqual(det["data_origin"], "tier_b_real_spherex_field_analysis")

        r_bad_cat = client.get("/api/field/search", params={"categories": "bad_category"})
        self.assertEqual(r_bad_cat.status_code, 422)

        r_404 = client.get("/api/field/w1925/source/NONEXISTENT-999")
        self.assertEqual(r_404.status_code, 404)

        # Repeated slider sweeps across /api/field/search must keep LRU cache bounded
        for step in range(140):
            r_sweep = client.get("/api/field/search", params={"field_id": "all", "min_snr": round(step * 0.25, 2), "limit": 5})
            self.assertEqual(r_sweep.status_code, 200)
        self.assertLessEqual(len(app.state.search_cache), 128)

    def test_t51_t52_ui_offline_search_and_identity_v2(self):
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as hf:
            html = hf.read()
        self.assertIn('id="search-light-panel"', html)
        self.assertIn('id="identity-v2-card"', html)
        self.assertIn('id="identity-strip-canvas"', html)
        self.assertIn('id="model-card-modal"', html)
        for cat in SEARCH_CATEGORY_FILTERS:
            self.assertIn(f'data-cat="{cat["id"]}"', html)

        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for UI harness test")

        viewer_js_path = os.path.join(STATIC_DIR, "viewer.js")
        fallback_js_path = os.path.join(STATIC_DIR, "fallback_data.js")
        js_harness = r"""
const fs = require('fs');
const vm = require('vm');
const fallbackSrc = fs.readFileSync(process.argv[1], 'utf8');
const viewerSrc = fs.readFileSync(process.argv[2], 'utf8');

function makeClassList(initial) {
  const s = new Set(initial || []);
  return {
    toggle(c, force) { if (force === undefined) { s.has(c) ? s.delete(c) : s.add(c); } else if (force) s.add(c); else s.delete(c); },
    contains(c) { return s.has(c); },
  };
}
function makeEl(id, extra) {
  const listeners = {};
  const attrs = {};
  return Object.assign({
    id, value: '', checked: false, hidden: false, disabled: false, textContent: '', children: [],
    width: 256, height: 256, dataset: {}, classList: makeClassList([]),
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k]; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatch(ev, payload) { (listeners[ev] || []).forEach((fn) => fn(payload || {})); },
    replaceChildren(...nodes) { this.children = nodes; },
    append(...nodes) { this.children.push(...nodes); },
    appendChild(n) { this.children.push(n); return n; },
    getContext() {
      return {
        fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
        fillRect() {}, clearRect() {}, strokeRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {}, fill() {}, fillText() {},
        createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
        putImageData() {}, drawImage() {},
      };
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 256, height: 256 }; },
  }, extra || {});
}

const byId = {
  'sky-query-form': makeEl('sky-query-form'),
  'coord-input': makeEl('coord-input', { value: 'WISE 0855' }),
  'fov-select': makeEl('fov-select', { value: '6.5', options: [{ value: '6.5' }] }),
  'epoch-input': makeEl('epoch-input', { value: '2026.0' }),
  'live-toggle': makeEl('live-toggle', { checked: false }),
  'mode-badge': makeEl('mode-badge'),
  'status-banner': makeEl('status-banner'),
  'sky-canvas': makeEl('sky-canvas'),
  'spectrum-canvas': makeEl('spectrum-canvas'),
  'matrix-canvas': makeEl('matrix-canvas'),
  'lightcurve-canvas': makeEl('lightcurve-canvas'),
  'play-toggle': makeEl('play-toggle'),
  'visit-scrubber': makeEl('visit-scrubber', { value: '0' }),
  'visit-label': makeEl('visit-label'),
  'stretch-select': makeEl('stretch-select', { value: 'asinh' }),
  'speed-select': makeEl('speed-select', { value: '750' }),
  'gaia-overlay-toggle': makeEl('gaia-overlay-toggle', { checked: true }),
  'mask-overlay-toggle': makeEl('mask-overlay-toggle', { checked: true }),
  'invert-toggle': makeEl('invert-toggle', { checked: false }),
  'follow-motion-toggle': makeEl('follow-motion-toggle', { checked: false }),
  'inject-toggle': makeEl('inject-toggle', { checked: false }),
  'export-png-btn': makeEl('export-png-btn'),
  'export-csv-btn': makeEl('export-csv-btn'),
  'external-links': makeEl('external-links'),
  'motion-summary': makeEl('motion-summary'),
  'change-spectrum-list': makeEl('change-spectrum-list'),
  'sso-input': makeEl('sso-input'),
  'sso-query-btn': makeEl('sso-query-btn'),
  'sso-status': makeEl('sso-status'),
  'proof-summary-body': makeEl('proof-summary-body'),
  'pixel-readout': makeEl('pixel-readout'),
  'molecule-list': makeEl('molecule-list'),
  'frames-tbody': makeEl('frames-tbody'),
  'frames-heading': makeEl('frames-heading'),
  'spectrum-heading': makeEl('spectrum-heading'),
  'copy-url-btn': makeEl('copy-url-btn'),
  'remove-known-row': makeEl('remove-known-row', { hidden: true }),
  'search-coverage-note': makeEl('search-coverage-note'),
  'search-match-count': makeEl('search-match-count'),
  'search-field-scope': makeEl('search-field-scope', { value: 'all' }),
  'search-min-snr': makeEl('search-min-snr', { value: '5' }),
  'search-min-snr-val': makeEl('search-min-snr-val'),
  'search-max-blend': makeEl('search-max-blend', { value: '1.0' }),
  'search-max-blend-val': makeEl('search-max-blend-val'),
  'search-unexplained-only': makeEl('search-unexplained-only', { checked: false }),
  'search-sort-select': makeEl('search-sort-select', { value: 'priority' }),
  'search-results-list': makeEl('search-results-list'),
  'identity-v2-card': makeEl('identity-v2-card', { hidden: true }),
  'identity-v2-title': makeEl('identity-v2-title'),
  'identity-v2-header': makeEl('identity-v2-header'),
  'identity-v2-bands': makeEl('identity-v2-bands'),
  'identity-strip-canvas': makeEl('identity-strip-canvas'),
  'identity-v2-top3': makeEl('identity-v2-top3'),
  'identity-v2-checks': makeEl('identity-v2-checks'),
  'identity-v2-meta': makeEl('identity-v2-meta'),
  'model-card-open-btn': makeEl('model-card-open-btn'),
  'model-card-modal': makeEl('model-card-modal', { hidden: true }),
  'model-card-close-btn': makeEl('model-card-close-btn'),
  'model-card-body': makeEl('model-card-body'),
};

const varBtn = makeEl('', { dataset: { cat: 'variable_source' }, classList: makeClassList(['search-cat-btn']) });
const ch4Btn = makeEl('', { dataset: { cat: 'methane_dip' }, classList: makeClassList(['search-cat-btn']) });

const sandbox = {
  console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {}, URLSearchParams,
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  fetch: async () => { throw new Error('offline'); },
  window: {
    location: { search: '', pathname: '/' },
    history: { replaceState() {} },
    setInterval: () => 1,
    clearInterval() {},
    matchMedia: () => ({ matches: true }),
  },
  document: {
    getElementById(id) { return byId[id] || null; },
    querySelectorAll(sel) {
      if (sel === '.search-cat-btn') return [varBtn, ch4Btn];
      return [];
    },
    addEventListener() {},
    createElement(tag) { return makeEl(tag); },
    body: { appendChild() {} },
  },
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fallbackSrc, sandbox);
sandbox.__PHANTOM_STATIC_FALLBACK__.field_search.results.push(
  {
    source_id: 'TEST-CH4-PASS',
    field_id: 'w1925',
    field_name: 'W1925 Galactic Plane',
    kind: 'Catalogued source',
    snr: 25.0,
    blend_share: 0.05,
    p_real: 0.99,
    priority: 999.0,
    unexplained_score: 0.2,
    estimate_all_data: { top_class: 'Ultracool dwarf', confidence: 0.9, conformal_set: ['Ultracool dwarf'] },
    estimate_spectrum_alone: { top_class: 'Ultracool dwarf', confidence: 0.9, conformal_set: ['Ultracool dwarf'] },
    molecules: { status: 'MEASURED', features: { CH4_3_3: { status: 'MEASURED', integrated_tau: 45.0, p16: 40.0, p84: 50.0 } } },
  },
  {
    source_id: 'TEST-CH4-LOW-SNR',
    field_id: 'w1925',
    field_name: 'W1925 Galactic Plane',
    kind: 'Catalogued source',
    snr: 25.0,
    blend_share: 0.05,
    p_real: 0.99,
    priority: 998.0,
    unexplained_score: 0.2,
    estimate_all_data: { top_class: 'Star', confidence: 0.9, conformal_set: ['Star'] },
    estimate_spectrum_alone: { top_class: 'Star', confidence: 0.9, conformal_set: ['Star'] },
    molecules: { status: 'MEASURED', features: { CH4_3_3: { status: 'MEASURED', integrated_tau: 35.0, p16: 10.0, p84: 60.0 } } },
  }
);
vm.runInNewContext(viewerSrc, sandbox);

(async () => {
  await new Promise((r) => setTimeout(r, 50));
  if (byId['search-results-list'].children.length < 5) {
    throw new Error('Expected Search-by-Light list populated offline, got ' + byId['search-results-list'].children.length);
  }
  if (!byId['search-coverage-note'].textContent.includes('full-sky catalog search not active')) {
    throw new Error('Missing honest coverage note: ' + byId['search-coverage-note'].textContent);
  }
  varBtn.dispatch('click');
  await new Promise((r) => setTimeout(r, 30));
  if (varBtn.getAttribute('aria-pressed') !== 'true') throw new Error('Expected variable filter pill pressed');
  const firstRow = byId['search-results-list'].children[0];
  if (!firstRow) throw new Error('Expected matching variable source offline');
  firstRow.dispatch('click');
  await new Promise((r) => setTimeout(r, 40));
  if (byId['identity-v2-card'].hidden !== false) throw new Error('Identity v2 card should unhide on source click');
  if (byId['identity-v2-checks'].children.length < 4) throw new Error('Expected Identity v2 machine check pills');
  if (byId['identity-v2-header'].children.length < 2) throw new Error('Expected Identity v2 spectral sampling warning');

  byId['model-card-open-btn'].dispatch('click');
  if (byId['model-card-modal'].hidden !== false) throw new Error('Expected Model Card modal open');
  if (!byId['model-card-body'].children.some((p) => p.textContent.includes('M1 artefact screen'))) {
    throw new Error('Missing M1 calibration line inside Model Card modal');
  }
  byId['model-card-close-btn'].dispatch('click');
  if (byId['model-card-modal'].hidden !== true) throw new Error('Expected Model Card modal closed');

  // Toggle variable off and methane_dip on to verify offline CH4_3_3 schema parity with backend
  varBtn.dispatch('click');
  ch4Btn.dispatch('click');
  await new Promise((r) => setTimeout(r, 30));
  const ch4Ids = byId['search-results-list'].children.map((b) => (b.children[0] && b.children[0].textContent) || '');
  if (!ch4Ids.some((t) => t.startsWith('TEST-CH4-PASS'))) {
    throw new Error('Expected methane_dip offline filter to match valid CH4_3_3 integrated_tau record, got ' + JSON.stringify(ch4Ids));
  }
  if (ch4Ids.some((t) => t.startsWith('TEST-CH4-LOW-SNR'))) {
    throw new Error('Expected methane_dip offline filter to reject low-S/N CH4_3_3 record');
  }
  // Rapid slider input must coalesce via 150ms debounce cleanly without error
  ch4Btn.dispatch('click');
  byId['search-min-snr'].value = '12';
  byId['search-min-snr'].dispatch('input');
  byId['search-min-snr'].value = '20';
  byId['search-min-snr'].dispatch('input');
  await new Promise((r) => setTimeout(r, 200));
  if (byId['search-min-snr-val'].textContent !== '20') {
    throw new Error('Expected debounced min_snr label to update cleanly');
  }
  console.log('T51_T52_OFFLINE_OK');
})();
"""
        proc = subprocess.run(
            [node, "-e", js_harness, fallback_js_path, viewer_js_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"Node T51/T52 UI failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        self.assertIn("T51_T52_OFFLINE_OK", proc.stdout)

    def test_ml_pipeline_single_fit_shared_and_lifespan_prewarm(self):
        import concurrent.futures
        import os
        import threading
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from phantom_worlds import api as api_mod
        from phantom_worlds import tier_b_detectors
        from phantom_worlds.contracts import load_spectra_table

        spectra_ref = load_spectra_table(api_mod.DEFAULT_CSV_DIR)
        cached_bundle = tier_b_detectors.get_cached_ml_pipeline(api_mod.DEFAULT_REAL_DATASET_NPZ)
        api_pipe, api_origin = api_mod._build_default_discovery_pipeline(
            spectra_ref,
            dataset_npz_path=api_mod.DEFAULT_REAL_DATASET_NPZ,
        )
        self.assertEqual(api_origin, "real_spherex_dr1_spiff_trained")
        self.assertIs(api_pipe, cached_bundle["pipeline"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: tier_b_detectors.analyze_field_candidates("rwaur"), range(4)))
        self.assertTrue(all(r is results[0] for r in results))

        orig_thread = threading.Thread
        started_names = []

        class RecordingThread:
            def __init__(self, *args, **kwargs):
                started_names.append(kwargs.get("name"))
                self._inner = orig_thread(*args, **kwargs)

            def start(self):
                self._inner.start()

        with patch.dict(os.environ, {"PHANTOM_DISABLE_PREWARM": "1"}), patch.object(api_mod.threading, "Thread", RecordingThread):
            with TestClient(api_mod.create_app()) as client_no_warm:
                self.assertEqual(client_no_warm.get("/health").status_code, 200)
                self.assertFalse(client_no_warm.app.state.prewarm_stop.is_set())
            self.assertTrue(client_no_warm.app.state.prewarm_stop.is_set())
        self.assertNotIn("phantom-prewarm", started_names)

        started_names.clear()
        env_no_disable = {k: v for k, v in os.environ.items() if k != "PHANTOM_DISABLE_PREWARM"}
        with patch.dict(os.environ, env_no_disable, clear=True), patch.object(api_mod.threading, "Thread", RecordingThread):
            with TestClient(api_mod.create_app()) as client_warm:
                self.assertEqual(client_warm.get("/health").status_code, 200)
            self.assertTrue(client_warm.app.state.prewarm_stop.is_set())
        self.assertIn("phantom-prewarm", started_names)

    def test_backend_autoloads_exported_checkpoint_and_falls_back_when_stale(self):
        import os
        import shutil
        import tempfile
        from unittest.mock import patch
        from phantom_worlds import api as api_mod
        from phantom_worlds import tier_b_detectors
        from phantom_worlds.ml_pipeline import CHECKPOINT_FILENAME, CHECKPOINT_META_FILENAME

        d_path = os.path.abspath(api_mod.DEFAULT_REAL_DATASET_NPZ)
        ckpt_path = os.path.join(os.path.dirname(d_path), CHECKPOINT_FILENAME)
        meta_path = os.path.join(os.path.dirname(d_path), CHECKPOINT_META_FILENAME)
        self.assertTrue(os.path.exists(ckpt_path), f"Missing exported checkpoint: {ckpt_path}")
        self.assertTrue(os.path.exists(meta_path), f"Missing checkpoint metadata: {meta_path}")

        with tier_b_detectors._CACHE_LOCK:
            saved_cache = dict(tier_b_detectors._TRAINED_PIPE_CACHE)
            tier_b_detectors._TRAINED_PIPE_CACHE.clear()
        try:
            with patch.object(
                tier_b_detectors,
                "train_from_real_dataset",
                side_effect=AssertionError("Should auto-load exported checkpoint without fitting"),
            ):
                bundle = tier_b_detectors.get_cached_ml_pipeline(d_path)
            self.assertEqual(bundle["load_source"], "disk_checkpoint")
            self.assertTrue(bundle["pipeline"].fitted_)

            # When checkpoint is absent or stale for a dataset, backend falls back to live fit.
            with tempfile.TemporaryDirectory() as tmpdir:
                copy_npz = os.path.join(tmpdir, "real_training_dataset.npz")
                shutil.copy2(d_path, copy_npz)
                with patch.object(
                    tier_b_detectors,
                    "train_from_real_dataset",
                    wraps=tier_b_detectors.train_from_real_dataset,
                ) as spy_fit:
                    fallback_bundle = tier_b_detectors.get_cached_ml_pipeline(copy_npz)
                self.assertEqual(spy_fit.call_count, 1)
                self.assertEqual(fallback_bundle["load_source"], "live_fit")
                self.assertTrue(fallback_bundle["pipeline"].fitted_)
                with tier_b_detectors._CACHE_LOCK:
                    tier_b_detectors._TRAINED_PIPE_CACHE.pop(os.path.abspath(copy_npz), None)
        finally:
            with tier_b_detectors._CACHE_LOCK:
                tier_b_detectors._TRAINED_PIPE_CACHE.clear()
                tier_b_detectors._TRAINED_PIPE_CACHE.update(saved_cache)
