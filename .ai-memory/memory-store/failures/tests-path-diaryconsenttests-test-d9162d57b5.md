---
store_path: failures/tests-path-diaryconsenttests-test-d9162d57b5
title: "tests/test_diary.py DiaryConsentTests.test_approve_writes_diary_json_under_home "
summary: "tests/test_diary.py DiaryConsentTests.test_approve_writes_diary_json_under_home and test_status_reports_off_by_default failed on macOS and Windows: AssertionError False is not true / 'C:\\Users\\RUNNER~"
priority: medium
tags: [ci, diary, failure, fix, macos, paths, windows]
schema_version: 1.3
last_updated: "2026-08-18T20:21:04-04:00"
occurrences: 1
error_signature: "tests<path> diaryconsenttests.test_approve_writes_diary_json_under_home and test_status_reports_off_by_default failed on macos and windows: assertionerror false is not true / <val> not found in <val>. str(consent_path()).startswith(str(self.home)) and assertin(str(self.home), consent_path) compared "
failure_key: assertionerror
---

## Occurrence 1 — 2026-08-18T20:21:04-04:00

**Error:**
tests/test_diary.py DiaryConsentTests.test_approve_writes_diary_json_under_home and test_status_reports_off_by_default failed on macOS and Windows: AssertionError False is not true / 'C:\Users\RUNNER~1\...\mf-home' not found in 'C:\Users\runneradmin\...\mf-home\diary.json'. str(consent_path()).startswith(str(self.home)) and assertIn(str(self.home), consent_path) compared the unresolved tempfile path to get_global_root() which Path.resolve()s MEMORY_FABRIC_HOME.

**Fix:**
In diary tests, resolve the tempfile root before setting MEMORY_FABRIC_HOME, and compare with Path.resolve().is_relative_to(home.resolve()) instead of string prefix/substring. That canonicalizes macOS /var vs /private/var and Windows 8.3 RUNNER~1 vs runneradmin.
