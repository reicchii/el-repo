"""Phantom Worlds — Tier B machine-learning architecture.

Implements the M1 (artefact gate), M2 (two-level type classifier + experts +
combiner + conformal sets) and M3 (novelty / discovery ontology) models, plus
the synthetic training library and the citizen-science case router.

Every module sets ``OPENBLAS_NUM_THREADS=1`` before importing numpy — see the
project tooling rules for why this is required on this Windows laptop.
"""

from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from . import constants  # noqa: E402,F401