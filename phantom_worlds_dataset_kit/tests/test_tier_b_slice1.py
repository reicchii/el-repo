"""Tests for Tier-B Slice 1: T40 Reference Scenes, T41 Joint PSF Deblending, and T50 UI Toggle."""

import json
import os
import shutil
import subprocess
import unittest

from fastapi.testclient import TestClient
import numpy as np

from phantom_worlds.api import create_app
from phantom_worlds.contracts import DEFAULT_CONTRACTS_DIR
from phantom_worlds.fits_cutout import _MJY_SR_TO_UJY_PX, build_target_canvas_wcs
from phantom_worlds.tier_b_engine import (
    DETECTOR_CWAVE_BOUNDS_UM,
    compute_field_remove_known,
    evaluate_b1_b2_2mass_check,
    evaluate_psf_patch,
    list_processed_fields,
    solve_joint_psf_frame,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATIC_DIR = os.path.join(REPO_ROOT, "phantom_worlds", "static")


class TestTierBSlice1Engine(unittest.TestCase):
    def test_joint_psf_deblends_overlapping_stars_and_respects_masks_and_bit21(self):
        wcs = build_target_canvas_wcs(291.30325, 7.01078, size_px=64, pixel_scale_arcsec=6.15)
        ra_a, dec_a = wcs.all_pix2world([[25.3, 28.4]], 0)[0]
        ra_b, dec_b = wcs.all_pix2world([[27.0, 29.1]], 0)[0]  # ~1.84 px from star A (heavily blended)
        ra_c, dec_c = wcs.all_pix2world([[48.0, 44.0]], 0)[0]

        sources = [
            {
                "source_id": "SYN-A",
                "catalogue": "GaiaDR3+2MASS",
                "ra_ref_deg": float(ra_a),
                "dec_ref_deg": float(dec_a),
                "ref_epoch": 2026.0,
                "pmra_mas_yr": 0.0,
                "pmdec_mas_yr": 0.0,
                "ks_mag": 11.0,
            },
            {
                "source_id": "SYN-B",
                "catalogue": "2MASS",
                "ra_ref_deg": float(ra_b),
                "dec_ref_deg": float(dec_b),
                "ref_epoch": 2026.0,
                "pmra_mas_yr": 0.0,
                "pmdec_mas_yr": 0.0,
                "ks_mag": 11.5,
            },
            {
                "source_id": "SYN-C",
                "catalogue": "GaiaDR3",
                "ra_ref_deg": float(ra_c),
                "dec_ref_deg": float(dec_c),
                "ref_epoch": 2026.0,
                "pmra_mas_yr": 0.0,
                "pmdec_mas_yr": 0.0,
                "ks_mag": 10.5,
            },
        ]

        ny = nx = 64
        img = np.full((ny, nx), 0.12, dtype=np.float64)
        true_sum_mjy = [60.0, 40.0, 80.0]
        pix_coords = [(25.3, 28.4), (27.0, 29.1), (48.0, 44.0)]
        for flux_tot, (xp, yp) in zip(true_sum_mjy, pix_coords):
            iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(ny, nx, xp, yp, half_box=4, sigma_px=0.58)
            img[iy0:iy1, ix0:ix1] += flux_tot * patch

        # Encode IRSA_REJECTED=1 on one wing pixel, while setting high bit 1<<7 (never masked in uint8 overlay -> low 3 bits = 0)
        # Verify mask bits (msk & 7) == 0 preserve source core light while corrupt pixel with bit 1 gets W=0
        msk = np.zeros((ny, nx), dtype=np.uint8)
        msk[44, 48] = 16  # non-7 flag bit must never zero out source core weight
        msk[44, 50] = 1   # IRSA_REJECTED=1 wing spike must get W=0 and NaN residual
        img[44, 50] = 9999.0

        solved = solve_joint_psf_frame(img, msk, wcs, sources, epoch_yr=2026.0, detector_id="D3", ridge_reg=1e-6)
        by_id = {s["source_id"]: s for s in solved["fitted_sources"]}
        self.assertEqual(len(by_id), 3)

        for sid, truth in zip(("SYN-A", "SYN-B", "SYN-C"), true_sum_mjy):
            expected_ujy = truth * _MJY_SR_TO_UJY_PX
            self.assertAlmostEqual(by_id[sid]["flux_uJy"], expected_ujy, delta=expected_ujy * 0.03)

        self.assertGreater(by_id["SYN-A"]["blend_share"], 0.08)
        self.assertGreater(by_id["SYN-B"]["blend_share"], by_id["SYN-A"]["blend_share"])
        self.assertLess(by_id["SYN-C"]["blend_share"], 0.02)
        self.assertTrue(np.isnan(solved["residual"][44, 50]))
        self.assertTrue(np.isfinite(solved["residual"][44, 48]))

    def test_real_field_scenes_and_b1_b2_evaluation(self):
        fields = list_processed_fields(DEFAULT_CONTRACTS_DIR)
        field_ids = {f["field_id"] for f in fields}
        self.assertEqual(field_ids, {"w1925", "rwaur"})

        rk_w = compute_field_remove_known("w1925", detector_id="D3", contracts_dir=DEFAULT_CONTRACTS_DIR)
        self.assertEqual(rk_w["cutout_origin"], "real_spherex_s3_wcs_cutout")
        self.assertEqual(rk_w["wavelength_range_um"], list(DETECTOR_CWAVE_BOUNDS_UM["D3"]))
        self.assertEqual(len(rk_w["image_stack"]), 64)
        self.assertEqual(len(rk_w["model_stack"]), 64)
        self.assertEqual(len(rk_w["residual_stack"]), 64)
        self.assertGreaterEqual(len(rk_w["fitted_sources"]), 100)

        b2 = evaluate_b1_b2_2mass_check("w1925", contracts_dir=DEFAULT_CONTRACTS_DIR)
        self.assertEqual(b2["status"], "MEASURED")
        self.assertGreaterEqual(b2["matched_count"], 20)
        self.assertTrue(b2["passed"], f"Expected W1925 B2 scatter <= 20%, got {b2}")

        b1 = evaluate_b1_b2_2mass_check("rwaur", contracts_dir=DEFAULT_CONTRACTS_DIR)
        self.assertEqual(b1["status"], "MEASURED")
        self.assertGreaterEqual(b1["matched_count"], 5)
        self.assertIsNotNone(b1["median_offset_pct"])
        self.assertIsNotNone(b1["scatter_pct"])


class TestTierBSlice1ApiAndUi(unittest.TestCase):
    def test_fields_and_remove_known_api_endpoints(self):
        app = create_app()
        client = TestClient(app)

        r_list = client.get("/api/fields")
        self.assertEqual(r_list.status_code, 200)
        ids = {f["field_id"] for f in r_list.json()["fields"]}
        self.assertEqual(ids, {"w1925", "rwaur"})

        r_rm = client.get("/api/field/w1925/remove_known", params={"detector": "D3"})
        self.assertEqual(r_rm.status_code, 200)
        body = r_rm.json()
        self.assertEqual(body["field_id"], "w1925")
        self.assertEqual(body["detector"], "D3")
        self.assertEqual(len(body["image_stack"]), 64)
        self.assertEqual(len(body["residual_stack"]), 64)

        r_404 = client.get("/api/field/not_a_field/remove_known")
        self.assertEqual(r_404.status_code, 404)

    def test_fallback_bundle_and_t50_ui_remove_known_offline(self):
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as hf:
            html = hf.read()
        self.assertIn('data-field="w1925"', html)
        self.assertIn('data-field="rwaur"', html)
        self.assertIn('id="remove-known-row"', html)
        for layer in ("image", "model", "residual"):
            self.assertIn(f'data-layer="{layer}"', html)

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
  'fov-select': makeEl('fov-select', { value: '6.5', options: [{ value: '3.0' }, { value: '6.5' }, { value: '12.0' }] }),
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
  'stretch-select': makeEl('stretch-select', { value: 'asinh', options: [{ value: 'asinh' }, { value: 'linear' }] }),
  'speed-select': makeEl('speed-select', { value: '750', options: [{ value: '300' }, { value: '750' }, { value: '1200' }] }),
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
};
const fieldW = makeEl('', { dataset: { field: 'w1925' }, classList: makeClassList(['preset-btn', 'field-btn']) });
const fieldR = makeEl('', { dataset: { field: 'rwaur' }, classList: makeClassList(['preset-btn', 'field-btn']) });
const rmImg = makeEl('', { dataset: { layer: 'image' }, classList: makeClassList(['rmknown-btn', 'active']) });
const rmMod = makeEl('', { dataset: { layer: 'model' }, classList: makeClassList(['rmknown-btn']) });
const rmRes = makeEl('', { dataset: { layer: 'residual' }, classList: makeClassList(['rmknown-btn']) });

const sandbox = {
  console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {}, URLSearchParams,
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  fetch: async () => { throw new Error('offline'); },
  window: {
    location: { search: '', pathname: '/' },
    history: { replaceState() {} },
    setInterval: () => 1,
    clearInterval() {},
    matchMedia: (q) => ({ matches: q.includes('prefers-reduced-motion') }),
  },
  document: {
    getElementById(id) { return byId[id] || null; },
    querySelectorAll(sel) {
      if (sel === '.preset-btn') return [fieldW, fieldR];
      if (sel === '.field-btn') return [fieldW, fieldR];
      if (sel === '.rmknown-btn') return [rmImg, rmMod, rmRes];
      return [];
    },
    createElement(tag) { return makeEl(tag); },
    body: { appendChild() {} },
  },
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fallbackSrc, sandbox);
vm.runInNewContext(viewerSrc, sandbox);

(async () => {
  await new Promise((r) => setTimeout(r, 40));
  if (byId['remove-known-row'].hidden !== true) throw new Error('Remove known row should start hidden on target');
  fieldW.dispatch('click');
  await new Promise((r) => setTimeout(r, 40));
  if (byId['remove-known-row'].hidden !== false) throw new Error('Remove known row should become visible on W1925');
  if (!fieldW.classList.contains('active')) throw new Error('W1925 field button should become active');
  if (!byId['visit-label'].textContent.includes('Image')) throw new Error('Visit label missing Image: ' + byId['visit-label'].textContent);
  rmRes.dispatch('click');
  if (rmRes.getAttribute('aria-pressed') !== 'true') throw new Error('Residual button should activate immediately on reduced motion');
  if (!byId['visit-label'].textContent.includes('Residual')) throw new Error('Visit label missing Residual');
  rmMod.dispatch('click');
  if (!byId['visit-label'].textContent.includes('Model')) throw new Error('Visit label missing Model');
  if (!sandbox.__PHANTOM_STATIC_FALLBACK__.fields.w1925.remove_known.D3) throw new Error('Missing offline W1925 D3');
  console.log('T50_OFFLINE_OK');
})();
"""
        proc = subprocess.run(
            [node, "-e", js_harness, fallback_js_path, viewer_js_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"Node UI failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        self.assertIn("T50_OFFLINE_OK", proc.stdout)
