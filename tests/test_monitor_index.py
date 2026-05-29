"""Unit tests for vibechecker.monitor.index.SessionIndex."""

import json
import threading
from pathlib import Path

import pytest
from vibechecker.monitor.index import SessionIndex


@pytest.fixture
def idx(tmp_path):
    si = SessionIndex(tmp_path)
    yield si
    si.close()


def _add(idx: SessionIndex, capture_id: str, trigger: str = 'interval',
         ts: str = '2026-05-28T10:00:00+00:00', rel_time: float = 0.0,
         overall: dict | None = None, peaks: dict | None = None) -> None:
    idx.add_capture(
        capture_id=capture_id,
        timestamp=ts,
        rel_time=rel_time,
        trigger=trigger,
        n_channels=2,
        samplerate=4096,
        overall=overall if overall is not None else {'0': 0.1, '1': 0.2},
        peaks=peaks if peaks is not None else {'0': [[10.0, 0.05], [20.0, 0.03]], '1': []},
    )


class TestCRUD:
    def test_add_and_count(self, idx):
        assert idx.count() == 0
        _add(idx, 'cap1')
        assert idx.count() == 1

    def test_idempotent_replace(self, idx):
        _add(idx, 'cap1')
        _add(idx, 'cap1')
        assert idx.count() == 1

    def test_query_returns_all(self, idx):
        _add(idx, 'cap1', ts='2026-05-28T10:00:00+00:00')
        _add(idx, 'cap2', ts='2026-05-28T11:00:00+00:00')
        rows = idx.query()
        assert len(rows) == 2

    def test_query_filter_trigger(self, idx):
        _add(idx, 'cap1', trigger='interval', ts='2026-05-28T10:00:00+00:00')
        _add(idx, 'cap2', trigger='burst',    ts='2026-05-28T11:00:00+00:00')
        rows = idx.query(trigger='burst')
        assert len(rows) == 1
        assert rows[0]['capture_id'] == 'cap2'

    def test_query_filter_time_range(self, idx):
        _add(idx, 'cap1', ts='2026-05-28T08:00:00+00:00')
        _add(idx, 'cap2', ts='2026-05-28T10:00:00+00:00')
        _add(idx, 'cap3', ts='2026-05-28T12:00:00+00:00')
        rows = idx.query(start_ts='2026-05-28T09:00:00+00:00',
                         end_ts='2026-05-28T11:00:00+00:00')
        assert len(rows) == 1
        assert rows[0]['capture_id'] == 'cap2'

    def test_query_pagination(self, idx):
        for i in range(5):
            _add(idx, f'cap{i}', ts=f'2026-05-28T{10+i:02d}:00:00+00:00')
        page1 = idx.query(limit=3, offset=0)
        page2 = idx.query(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

    def test_query_ordered_by_timestamp(self, idx):
        _add(idx, 'cap2', ts='2026-05-28T11:00:00+00:00')
        _add(idx, 'cap1', ts='2026-05-28T10:00:00+00:00')
        rows = idx.query()
        assert rows[0]['capture_id'] == 'cap1'
        assert rows[1]['capture_id'] == 'cap2'

    def test_overall_json_round_trip(self, idx):
        _add(idx, 'cap1', overall={'0': 0.123, '1': 0.456})
        rows = idx.query()
        assert rows[0]['overall'] == pytest.approx({'0': 0.123, '1': 0.456}, rel=1e-6)

    def test_peaks_json_round_trip(self, idx):
        peaks = {'0': [[100.0, 0.05], [200.0, 0.03]], '1': []}
        _add(idx, 'cap1', peaks=peaks)
        rows = idx.query()
        assert rows[0]['peaks'] == peaks

    def test_empty_overall_and_peaks(self, idx):
        _add(idx, 'cap1', overall={}, peaks={})
        rows = idx.query()
        assert rows[0]['overall'] == {}
        assert rows[0]['peaks'] == {}


class TestSessionMeta:
    def test_set_and_get(self, idx):
        idx.set_meta('session_id', 'test-123')
        assert idx.get_meta('session_id') == 'test-123'

    def test_get_missing_returns_none(self, idx):
        assert idx.get_meta('nonexistent') is None

    def test_overwrite(self, idx):
        idx.set_meta('key', 'v1')
        idx.set_meta('key', 'v2')
        assert idx.get_meta('key') == 'v2'


class TestTotalBytes:
    def test_returns_zero_on_fresh_index(self, tmp_path):
        # The file is created by __init__; it should exist but be small
        si = SessionIndex(tmp_path)
        assert si.total_bytes() > 0
        si.close()

    def test_grows_after_add(self, idx, tmp_path):
        before = idx.total_bytes()
        _add(idx, 'cap1')
        after = idx.total_bytes()
        assert after >= before


class TestConcurrentReadWrite:
    def test_concurrent_writes_no_crash(self, idx):
        errors = []

        def writer(n):
            try:
                for i in range(n):
                    _add(idx, f'thread-cap-{threading.get_ident()}-{i}',
                         ts=f'2026-05-28T10:{i:02d}:00+00:00')
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(10,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert idx.count() == 40

    def test_concurrent_read_write(self, idx):
        """Reads should not block while writes are happening (WAL mode)."""
        results = []
        errors = []

        def writer():
            try:
                for i in range(20):
                    _add(idx, f'w-{i}', ts=f'2026-05-28T{10+i//60:02d}:{i%60:02d}:00+00:00')
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    results.append(idx.count())
            except Exception as e:
                errors.append(e)

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start(); rt.start()
        wt.join(); rt.join()

        assert not errors
