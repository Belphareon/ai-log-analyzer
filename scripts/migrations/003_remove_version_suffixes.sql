-- Migration: Remove version suffixes from detection_method values
-- Date: 2026-02-25
-- Purpose: Normalize detection_method identifiers (v6_backfill → backfill, v6_regular → regular)
--
-- USAGE:
-- Run once after deploying the version-suffix-free codebase.
-- Safe to run multiple times (idempotent).

-- ============================================================================
-- UPDATE detection_method values
-- ============================================================================
UPDATE ailog_peak.peak_investigation
SET detection_method = 'backfill'
WHERE detection_method = 'v6_backfill';

UPDATE ailog_peak.peak_investigation
SET detection_method = 'regular'
WHERE detection_method = 'v6_regular';

-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT detection_method, COUNT(*)
-- FROM ailog_peak.peak_investigation
-- GROUP BY detection_method
-- ORDER BY detection_method;
