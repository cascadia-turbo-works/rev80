import json
import sqlite3
import threading
from pathlib import Path


class SessionIndex:
    def __init__(self, session_dir: Path):
        self._path = session_dir / 'index.sqlite'
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript('''
            CREATE TABLE IF NOT EXISTS captures (
                id           INTEGER PRIMARY KEY,
                capture_id   TEXT UNIQUE NOT NULL,
                timestamp    TEXT NOT NULL,
                rel_time     REAL NOT NULL,
                trigger      TEXT NOT NULL,
                n_channels   INTEGER NOT NULL,
                samplerate   INTEGER NOT NULL,
                overall_json TEXT,
                peaks_json   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ts ON captures(timestamp);
            CREATE TABLE IF NOT EXISTS session_meta (
                key TEXT PRIMARY KEY, value TEXT
            );
        ''')
        self._conn.commit()

    def add_capture(self, capture_id: str, timestamp: str, rel_time: float,
                    trigger: str, n_channels: int, samplerate: int,
                    overall: dict, peaks: dict) -> None:
        with self._lock:
            self._conn.execute(
                '''INSERT OR REPLACE INTO captures
                   (capture_id, timestamp, rel_time, trigger, n_channels, samplerate,
                    overall_json, peaks_json)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (capture_id, timestamp, rel_time, trigger, n_channels, samplerate,
                 json.dumps(overall), json.dumps(peaks))
            )
            self._conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                'INSERT OR REPLACE INTO session_meta (key, value) VALUES (?,?)',
                (key, value)
            )
            self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                'SELECT value FROM session_meta WHERE key=?', (key,)
            ).fetchone()
        return row[0] if row else None

    def query(self, start_ts: str | None = None, end_ts: str | None = None,
              trigger: str | None = None, limit: int = 100,
              offset: int = 0) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if start_ts:
            clauses.append('timestamp >= ?')
            params.append(start_ts)
        if end_ts:
            clauses.append('timestamp <= ?')
            params.append(end_ts)
        if trigger:
            clauses.append('trigger = ?')
            params.append(trigger)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(
                f'SELECT capture_id, timestamp, rel_time, trigger, n_channels, '
                f'samplerate, overall_json, peaks_json '
                f'FROM captures {where} ORDER BY timestamp LIMIT ? OFFSET ?',
                params
            ).fetchall()
        return [
            {
                'capture_id': r[0], 'timestamp': r[1], 'rel_time': r[2],
                'trigger': r[3], 'n_channels': r[4], 'samplerate': r[5],
                'overall': json.loads(r[6]) if r[6] else {},
                'peaks':   json.loads(r[7]) if r[7] else {},
            }
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute('SELECT COUNT(*) FROM captures').fetchone()[0]

    def total_bytes(self) -> int:
        return self._path.stat().st_size if self._path.exists() else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
