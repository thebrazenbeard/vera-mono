"""Parameterized SQL adapter for ``public.vera_coordination_events``.

This module does not open a network connection or contain credentials. A
runtime must supply an explicitly authorized executor. Generated columns are
intentionally omitted from inserts and returned by the database.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .contracts import CoordinationEvent, CoordinationEventDraft, CoordinationRepository

TABLE = "public.vera_coordination_events"
SELECT_COLUMNS = """
    event_id, event_sequence, thread_key, source_branch, target_branch,
    event_type, status, objective, summary, active_issue,
    requested_perspective, supersedes_event_id, acknowledges_event_id,
    payload, reference_data, record_time
""".strip()

GET_EVENT_SQL = f"""
select {SELECT_COLUMNS}
from {TABLE}
where event_id = %(event_id)s::uuid
limit 1;
""".strip()

LIST_THREAD_SQL = f"""
select {SELECT_COLUMNS}
from {TABLE}
where thread_key = %(thread_key)s
order by event_sequence asc;
""".strip()

READ_INBOX_SQL = f"""
select {SELECT_COLUMNS}
from {TABLE} as event
where event.target_branch = %(target_branch)s
  and event.event_sequence > %(after_sequence)s
  and (
      %(include_acknowledged)s
      or not exists (
          select 1
          from {TABLE} as response
          where response.source_branch = %(target_branch)s
            and response.acknowledges_event_id = event.event_id
      )
  )
order by event.event_sequence asc
limit %(limit)s;
""".strip()

INSERT_EVENT_SQL = f"""
insert into {TABLE} (
    thread_key, source_branch, target_branch, event_type, status,
    objective, summary, active_issue, requested_perspective,
    supersedes_event_id, acknowledges_event_id, payload, reference_data
) values (
    %(thread_key)s, %(source_branch)s, %(target_branch)s, %(event_type)s,
    %(status)s, %(objective)s, %(summary)s, %(active_issue)s,
    %(requested_perspective)s, %(supersedes_event_id)s::uuid,
    %(acknowledges_event_id)s::uuid, %(payload)s::jsonb,
    %(reference_data)s::jsonb
)
returning {SELECT_COLUMNS};
""".strip()

LIVE_SCHEMA_SNAPSHOT_V1: dict[str, Any] = {
    "table": TABLE,
    "observed_at": "2026-07-30T21:13:00Z",
    "generated_columns": {
        "event_id": "gen_random_uuid()",
        "event_sequence": "GENERATED ALWAYS AS IDENTITY",
        "record_time": "assigned by trigger/default clock_timestamp()",
    },
    "append_only": {"updates_blocked": True, "deletes_blocked": True},
    "client_access": {
        "anon": "DENIED_BY_RESTRICTIVE_RLS",
        "authenticated": "DENIED_BY_RESTRICTIVE_RLS",
    },
    "foreign_keys": {
        "acknowledges_event_id": "vera_coordination_events.event_id",
        "supersedes_event_id": "vera_coordination_events.event_id",
    },
    "one_successor_per_superseded_event": True,
}


def insert_params(draft: CoordinationEventDraft) -> dict[str, Any]:
    draft.validate()
    data = draft.canonical_dict()
    data["payload"] = json.dumps(
        data["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    data["reference_data"] = json.dumps(
        data["reference_data"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return data


class SqlExecutor:
    """Interface supplied by an authorized runtime database adapter."""

    def fetch_one(
        self, sql: str, params: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:  # pragma: no cover
        raise NotImplementedError

    def fetch_all(
        self, sql: str, params: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:  # pragma: no cover
        raise NotImplementedError


class SupabaseSqlRepository(CoordinationRepository):
    """Repository implementation over an injected parameter-binding executor."""

    def __init__(self, executor: SqlExecutor) -> None:
        self.executor = executor

    def append(self, draft: CoordinationEventDraft) -> CoordinationEvent:
        row = self.executor.fetch_one(INSERT_EVENT_SQL, insert_params(draft))
        if row is None:
            raise RuntimeError("insert returned no row; write is unconfirmed")
        return CoordinationEvent.from_row(row)

    def get(self, event_id: str) -> CoordinationEvent | None:
        row = self.executor.fetch_one(GET_EVENT_SQL, {"event_id": event_id})
        return None if row is None else CoordinationEvent.from_row(row)

    def list_thread(self, thread_key: str) -> tuple[CoordinationEvent, ...]:
        rows = self.executor.fetch_all(LIST_THREAD_SQL, {"thread_key": thread_key})
        return tuple(CoordinationEvent.from_row(row) for row in rows)

    def read_inbox(
        self,
        target_branch: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        include_acknowledged: bool = False,
    ) -> tuple[CoordinationEvent, ...]:
        rows = self.executor.fetch_all(
            READ_INBOX_SQL,
            {
                "target_branch": target_branch,
                "after_sequence": after_sequence,
                "limit": limit,
                "include_acknowledged": include_acknowledged,
            },
        )
        return tuple(CoordinationEvent.from_row(row) for row in rows)
