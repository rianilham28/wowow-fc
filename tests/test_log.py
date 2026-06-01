"""Tests for src/log.py — Log class timing behavior."""

import time

from src.log import Log


class TestLogTiming:
    def test_step_sets_t0(self):
        log = Log(index=1, total=1)
        assert log._t0 is None
        log.step("doing something")
        assert log._t0 is not None
        assert log._t0 > 0

    def test_done_returns_elapsed_time(self):
        log = Log(index=1, total=1)
        log.step("task")
        time.sleep(0.05)
        elapsed = log.done()
        assert elapsed >= 0.04  # allow some timing slack
        assert isinstance(elapsed, float)

    def test_fail_returns_elapsed_time(self):
        log = Log(index=1, total=1)
        log.step("task")
        time.sleep(0.05)
        elapsed = log.fail("something broke")
        assert elapsed >= 0.04
        assert isinstance(elapsed, float)

    def test_done_clears_t0(self):
        log = Log(index=1, total=1)
        log.step("task")
        log.done()
        assert log._t0 is None

    def test_fail_clears_t0(self):
        log = Log(index=1, total=1)
        log.step("task")
        log.fail()
        assert log._t0 is None

    def test_done_without_step_returns_zero(self):
        log = Log(index=1, total=1)
        elapsed = log.done()
        assert elapsed == 0.0

    def test_fail_without_step_returns_zero(self):
        log = Log(index=1, total=1)
        elapsed = log.fail()
        assert elapsed == 0.0

    def test_done_with_suffix(self):
        """Suffix should not affect return value."""
        log = Log(index=1, total=1)
        log.step("task")
        time.sleep(0.01)
        elapsed = log.done("extra info")
        assert elapsed > 0

    def test_info_clears_t0(self):
        log = Log(index=1, total=1)
        log.step("task")
        log.info("some info")
        assert log._t0 is None

    def test_ok_clears_t0(self):
        log = Log(index=1, total=1)
        log.step("task")
        log.ok("all good")
        assert log._t0 is None

    def test_error_clears_t0(self):
        log = Log(index=1, total=1)
        log.step("task")
        log.error("bad thing")
        assert log._t0 is None


class TestLogInit:
    def test_stores_index_and_total(self):
        log = Log(index=3, total=10)
        assert log._idx == 3
        assert log._total == 10

    def test_t0_initially_none(self):
        log = Log(index=1, total=1)
        assert log._t0 is None
