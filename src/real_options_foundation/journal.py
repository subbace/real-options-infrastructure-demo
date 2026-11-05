"""Exclusive-create durable JSONL journal; failed writes stop the sink."""

import os
from pathlib import Path

from .common import FoundationError, canonical_json_bytes, content_hash, freeze, note_event


class DurableJournal:
    def __init__(self, path: Path, *, opener=open, sync=os.fsync):
        self.path = Path(path)
        self._handle = opener(self.path, "xb")
        self._sync = sync
        self._seen = {}
        self._last_hash = "0" * 64
        self.failed = False

    @property
    def journal_hash(self):
        return self._last_hash

    def append(self, event_id, payload):
        note_event()
        if self.failed:
            raise FoundationError("Journal stopped after durable write failure")
        if not isinstance(event_id, str) or not event_id:
            raise FoundationError("Journal event identity is required")
        payload = freeze(payload)
        digest = content_hash(payload)
        if event_id in self._seen:
            if self._seen[event_id] != digest:
                raise FoundationError("Conflicting journal identity")
            return False
        record = {"event_id": event_id, "payload": payload, "previous_hash": self._last_hash}
        record_hash = content_hash(record)
        encoded = canonical_json_bytes(dict(record, record_hash=record_hash)) + b"\n"
        try:
            if self._handle.write(encoded) != len(encoded):
                raise OSError("Short durable write")
            self._handle.flush()
            self._sync(self._handle.fileno())
        except (OSError, ValueError) as exc:
            self.failed = True
            raise FoundationError("Durable write failed; preserve partial journal for inspection") from exc
        self._seen[event_id] = digest
        self._last_hash = record_hash
        return True

    def close(self):
        self._handle.close()


def validate_journal(path: Path):
    import json
    previous = "0" * 64
    identities = set()
    count = 0
    try:
        with Path(path).open("rb") as stream:
            for line in stream:
                note_event()
                if not line.endswith(b"\n"):
                    raise FoundationError("Truncated journal record")
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise FoundationError("Journal record must be an object")
                digest = record.pop("record_hash")
                if record["previous_hash"] != previous or content_hash(record) != digest:
                    raise FoundationError("Broken journal chain")
                if record["event_id"] in identities:
                    raise FoundationError("Duplicate durable record")
                identities.add(record["event_id"])
                previous = digest
                count += 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FoundationError("Invalid durable journal") from exc
    return {"records": count, "journal_hash": previous}
