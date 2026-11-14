"""Tests for Tier-B Slice 3: T46 B7 retro checks, T47 B8/B9 searched depth, T48 B1..B13 Proof v2, B4 methane, API & T53/T54 UI."""

import json
import os
import re
import shutil
import subprocess
import unittest

from fastapi.testclient import TestClient

from phantom_worlds.api import create_app
from phantom_worlds.contracts import DEFAULT_CONTRACTS_DIR
from phantom_worlds.tier_b_detectors import SEARCH_CATEGORY_FILTERS
from phantom_worlds.tier_b_proof import (
    DEFAULT_PROOF_DIR,
    INJECTION_MOTION_MODES,
    build_field_cases_queue,
    evaluate_b4_methane_benchmark,
    format_planet_x_statement,
    run_prediction_check,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATIC_DIR = os.path.join(REPO_ROOT, "phantom_worlds", "static")
FORBIDDEN_WORDS_RE = re.compile(r"\b(confirmed|discovered|verified)\b", re.IGNORECASE)


class TestTierBSlice3Engine(unittest.TestCase):
    def test_b7_prediction_check_and_retro_movers(self):
        res = run_prediction_check(contracts_dir=DEFAULT_CONTRACTS_DIR)
        b7 = res["b7_summary"]
        self.assertEqual(b7["movers_tested"], 3)
        by_id = {m["target_id"]: m for m in res["retro_movers"]}
        self.assertIn("TGT-01", by_id)
        self.assertIn("TGT-02", by_id)
        self.assertIn("TGT-03", by_id)

        # TGT-03 (Epsilon Indi B) clean unsaturated detector must honestly hold both pred <= 2*sigma and stay > 3*sigma
        t3 = by_id["TGT-03"]
        self.assertEqual(t3["status"], "held")
        self.assertTrue(t3["within_2sigma"])
        self.assertTrue(t3["stay_excluded_3sigma"])
        self.assertLessEqual(t3["pred_sep_arcsec"], 2.0 * t3["sigma_arcsec"] + 1e-6)
        self.assertGreater(t3["stay_sep_arcsec"], 3.0 * t3["sigma_stay_arcsec"])

        # Never fabricate or force TGT-02 / TGT-01 outcomes
        self.assertEqual(by_id["TGT-02"]["status"], "not_observed")
        self.assertIn("locked_predictions", res)
        if res["locked_predictions"]:
            lp = res["locked_predictions"][0]
            self.assertEqual(lp["status"], "pending")
            self.assertIn("predicted_ra_deg", lp)
            self.assertIn("stay_ra_deg", lp)

    def test_b4_methane_benchmark_measured(self):
        cat_ids = [c["id"] for c in SEARCH_CATEGORY_FILTERS]
        self.assertIn("methane_dip", cat_ids)
        b4 = evaluate_b4_methane_benchmark(contracts_dir=DEFAULT_CONTRACTS_DIR)
        self.assertEqual(b4["status"], "MEASURED")
        self.assertGreaterEqual(b4["t_dwarf_total"], 5)
        self.assertGreaterEqual(b4["recall"], 0.80)
        self.assertGreater(b4["neighbour_total"], 100)

    def test_t47_b8_b9_searched_depth_files_and_statement(self):
        searched_by_field = {}
        for fid in ("rwaur", "w1925"):
            spath = os.path.join(DEFAULT_CONTRACTS_DIR, "fields", fid, "searched.json")
            self.assertTrue(os.path.exists(spath), f"Missing {spath}")
            with open(spath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["schema_version"], "1.0.0-searched")
            self.assertIn("run_at", data)
            self.assertIn("pipeline_version", data)
            self.assertTrue(data["source_files"])
            for det in ("D3", "D6"):
                dtab = data["detectors"][det]
                self.assertEqual(len(dtab["motion_curves"]), len(INJECTION_MOTION_MODES))
                self.assertIsNotNone(dtab["depth_ab_50"])
            searched_by_field[fid] = data

        stmt = format_planet_x_statement(searched_by_field)
        self.assertEqual(stmt, searched_by_field["w1925"]["planet_x_statement"])
        self.assertIn("RW Aur", stmt)
        self.assertIn("W1925", stmt)
        self.assertIn("800\"", stmt)
        self.assertIsNone(FORBIDDEN_WORDS_RE.search(stmt), f"Reserved word in Planet X statement: {stmt}")

    def test_t48_proof_report_json_and_md_complete(self):
        rep_json = os.path.join(DEFAULT_PROOF_DIR, "report.json")
        rep_md = os.path.join(DEFAULT_PROOF_DIR, "report.md")
        self.assertTrue(os.path.exists(rep_json), "Missing proof/report.json")
        self.assertTrue(os.path.exists(rep_md), "Missing proof/report.md")

        with open(rep_json, "r", encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["schema_version"], "2.0.0-proof")
        tests = rep["tier_b_tests"]
        self.assertEqual([t["test_id"] for t in tests], [f"B{i}" for i in range(1, 14)])
        self.assertEqual(rep["counts"]["not_measured"], 0)

        by_tid = {t["test_id"]: t for t in tests}
        # Honest reported benchmarks from real outputs
        self.assertEqual(by_tid["B3"]["status"], "PASS")
        self.assertEqual(by_tid["B6"]["status"], "PASS")
        self.assertEqual(by_tid["B8"]["status"], "PASS")
        self.assertEqual(by_tid["B9"]["status"], "PASS")
        self.assertEqual(by_tid["B10"]["status"], "PASS")
        self.assertEqual(by_tid["B11"]["status"], "PASS")
        self.assertEqual(by_tid["B13"]["status"], "PASS")

        self.assertEqual(len(rep["tier_a_targets"]), 5)
        self.assertTrue(rep["stated_limits"])
        credits_blob = " ".join(f"{c['name']}: {c['detail']}" if isinstance(c, dict) else str(c) for c in rep["credits"])
        self.assertIn("10.26131/IRSA652", credits_blob)
        self.assertIn("10.5281/zenodo.19051216", credits_blob)

        with open(rep_md, "r", encoding="utf-8") as mf:
            md_txt = mf.read()
        self.assertIn("# Phantom Worlds — Proof Report v2", md_txt)
        for line in md_txt.splitlines():
            self.assertIsNone(
                FORBIDDEN_WORDS_RE.search(line),
                f"Forbidden reserved word in proof/report.md line: {line}",
            )


class TestTierBSlice3ApiAndUi(unittest.TestCase):
    def test_api_slice3_endpoints(self):
        app = create_app()
        client = TestClient(app)

        r_pred = client.get("/api/field/prediction_check")
        self.assertEqual(r_pred.status_code, 200)
        p_body = r_pred.json()
        self.assertIn("b7_summary", p_body)
        self.assertEqual(len(p_body["retro_movers"]), 3)

        r_sd_all = client.get("/api/field/searched")
        self.assertEqual(r_sd_all.status_code, 200)
        sd_body = r_sd_all.json()
        self.assertIn("w1925", sd_body["fields"])
        self.assertIn("rwaur", sd_body["fields"])
        self.assertIn("b9_smdet1", sd_body)

        r_sd_one = client.get("/api/field/searched", params={"field_id": "w1925"})
        self.assertEqual(r_sd_one.status_code, 200)
        self.assertEqual(list(r_sd_one.json()["fields"].keys()), ["w1925"])

        r_sd_bad = client.get("/api/field/searched", params={"field_id": "invalid_field"})
        self.assertEqual(r_sd_bad.status_code, 422)

        r_cases = client.get("/api/field/cases", params={"field_id": "w1925", "state": "Open signal"})
        self.assertEqual(r_cases.status_code, 200)
        c_body = r_cases.json()
        self.assertIn("cases", c_body)
        self.assertTrue(all(c["field_id"] == "w1925" and c["state"] == "Open signal" for c in c_body["cases"]))

        r_rep = client.get("/api/proof/report")
        self.assertEqual(r_rep.status_code, 200)
        rep_body = r_rep.json()
        self.assertEqual(rep_body["schema_version"], "2.0.0-proof")
        self.assertEqual(len(rep_body["tier_b_tests"]), 13)

    def test_t53_t54_offline_ui_cases_searched_depth_and_proof_v2(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node runtime unavailable")

        fallback_js_path = os.path.join(STATIC_DIR, "fallback_data.js")
        viewer_js_path = os.path.join(STATIC_DIR, "viewer.js")

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
    width: 520, height: 260, dataset: {}, classList: makeClassList([]),
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
        fillRect() {}, clearRect() {}, strokeRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {}, fill() {}, fillText() {}, setLineDash() {},
        createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
        putImageData() {}, drawImage() {},
      };
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 520, height: 260 }; },
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
  'searched-depth-layer-toggle': makeEl('searched-depth-layer-toggle', { checked: false }),
  'cases-count-badge': makeEl('cases-count-badge'),
  'signals-cases-list': makeEl('signals-cases-list'),
  'case-detail-box': makeEl('case-detail-box', { hidden: true }),
  'case-detail-title': makeEl('case-detail-title'),
  'case-detail-summary': makeEl('case-detail-summary'),
  'case-detail-checks': makeEl('case-detail-checks'),
  'case-flag-artefact-btn': makeEl('case-flag-artefact-btn'),
  'case-mark-explained-btn': makeEl('case-mark-explained-btn'),
  'case-reopen-btn': makeEl('case-reopen-btn'),
  'retro-prediction-summary': makeEl('retro-prediction-summary'),
  'retro-prediction-list': makeEl('retro-prediction-list'),
  'proof-v2-extra': makeEl('proof-v2-extra', { hidden: true }),
  'proof-report-card-wrap': makeEl('proof-report-card-wrap'),
  'recovery-curve-canvas': makeEl('recovery-curve-canvas'),
  'proof-ladder-wrap': makeEl('proof-ladder-wrap'),
  'proof-planet-x-statement': makeEl('proof-planet-x-statement'),
  'proof-credits-wrap': makeEl('proof-credits-wrap'),
};

const stateBtns = [
  makeEl('', { dataset: { state: 'all' }, classList: makeClassList(['case-state-btn', 'active']) }),
  makeEl('', { dataset: { state: 'Artefact' }, classList: makeClassList(['case-state-btn']) }),
  makeEl('', { dataset: { state: 'Open signal' }, classList: makeClassList(['case-state-btn']) }),
];

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
      if (sel === '.case-state-btn') return stateBtns;
      return [];
    },
    addEventListener() {},
    createElement(tag) { return makeEl(tag); },
    body: { appendChild() {} },
  },
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fallbackSrc, sandbox);
vm.runInNewContext(viewerSrc, sandbox);

(async () => {
  await new Promise((r) => setTimeout(r, 70));
  if (byId['proof-v2-extra'].hidden !== false) {
    throw new Error('Expected Proof v2 extra panel unhidden offline');
  }
  if (!byId['proof-planet-x-statement'].textContent.includes('RW Aur')) {
    throw new Error('Missing Planet X sensitivity statement in Proof v2');
  }
  if (!byId['proof-credits-wrap'].textContent.includes('10.26131/IRSA652')) {
    throw new Error('Missing section 13.5 DOIs in Proof credits');
  }
  if (byId['signals-cases-list'].children.length < 3) {
    throw new Error('Expected Signals & Cases queue populated offline, got ' + byId['signals-cases-list'].children.length);
  }
  if (byId['retro-prediction-list'].children.length !== 3) {
    throw new Error('Expected 3 B7 retro movers in UI, got ' + byId['retro-prediction-list'].children.length);
  }
  byId['case-flag-artefact-btn'].dispatch('click');
  await new Promise((r) => setTimeout(r, 20));
  if (!byId['case-detail-title'].textContent.includes('Artefact')) {
    throw new Error('Expected local case triage update to Artefact');
  }
  byId['searched-depth-layer-toggle'].checked = true;
  byId['searched-depth-layer-toggle'].dispatch('change');
  await new Promise((r) => setTimeout(r, 40));
  console.log('T53_T54_OFFLINE_OK');
})();
"""
        proc = subprocess.run(
            [node, "-e", js_harness, fallback_js_path, viewer_js_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, f"Node T53/T54 UI failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        self.assertIn("T53_T54_OFFLINE_OK", proc.stdout)
