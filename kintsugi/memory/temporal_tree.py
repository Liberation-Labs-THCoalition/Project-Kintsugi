"""Temporal-Semantic Tree — time-windowed memory consolidation.

Vendored and adapted from Project Mnemosyne's h-mem-temporal component.
Organizes memories in a tree where each level represents a time window
(hour, day, week, month). Within each window, semantically similar
memories are consolidated upward via LLM summary (see dreamer_consolidator.py).

The tree is built bottom-up during periodic consolidation. Query-time
traversal scopes to relevant levels based on SHORT/LONG/MIXED time scope.

Backed by its own SQLite database (path from settings.TEMPORAL_TREE_DB_PATH),
separate from the primary Postgres memory store — this is a lightweight,
purely local secondary index, not the authoritative memory record.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 86400
WEEK = 604800
MONTH = 2592000


class TimeScope(Enum):
    SHORT = "short"
    LONG = "long"
    MIXED = "mixed"


@dataclass
class TreeNode:
    """A node in the temporal-semantic tree."""
    id: int
    content: str
    timestamp: float
    level: int
    window_start: float
    window_end: float
    parent_id: int | None = None
    children_ids: list[int] = field(default_factory=list)
    reinforcement_count: int = 0
    last_reinforced: float = 0
    contradicted_by: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def age(self) -> float:
        return time.time() - self.timestamp

    @property
    def robustness(self) -> float:
        return ebbinghaus_decay(
            time.time(), self.last_reinforced or self.timestamp,
            self.reinforcement_count
        )


def ebbinghaus_decay(t: float, r_m: float, n_m: int,
                     tau: float = WEEK, eta: float = 0.5) -> float:
    """Ebbinghaus forgetting curve with reinforcement.

    Args:
        t: Current time (unix timestamp).
        r_m: Time of last reinforcement.
        n_m: Reinforcement count.
        tau: Base decay constant (default: 1 week).
        eta: Reinforcement scaling factor.

    Returns:
        Robustness score in [0, 1]. Higher = more robust.
    """
    elapsed = t - r_m
    if elapsed <= 0:
        return 1.0
    denominator = tau * (1 + eta * math.log(1 + n_m))
    return math.exp(-elapsed / denominator)


def temporal_iou(q_start: float, q_end: float,
                 m_start: float, m_end: float) -> float:
    """Temporal relevance via interval IoU + center distance."""
    intersection = max(0, min(q_end, m_end) - max(q_start, m_start))
    union = max(q_end, m_end) - min(q_start, m_start)
    if union <= 0:
        return 0.0
    iou = intersection / union

    q_center = (q_start + q_end) / 2
    m_center = (m_start + m_end) / 2
    max_dist = max(q_end - q_start, m_end - m_start, 1)
    center_score = 1 - min(abs(q_center - m_center) / max_dist, 1)

    return 0.7 * iou + 0.3 * center_score


LEVEL_WINDOWS = {
    0: 0,
    1: DAY,
    2: WEEK,
    3: MONTH,
    4: MONTH * 3,
}

LEVEL_SIMILARITY_THRESHOLDS = {
    1: 0.7,
    2: 0.5,
    3: 0.3,
    4: 0.2,
}


class TemporalTree:
    """Temporal-semantic tree backed by SQLite.

    Args:
        db_path: Path to the SQLite database file. Defaults to
            ``settings.TEMPORAL_TREE_DB_PATH`` when not given.
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from kintsugi.config.settings import settings
            db_path = settings.TEMPORAL_TREE_DB_PATH
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tree_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                level INTEGER NOT NULL DEFAULT 0,
                window_start REAL NOT NULL,
                window_end REAL NOT NULL,
                parent_id INTEGER,
                reinforcement_count INTEGER DEFAULT 0,
                last_reinforced REAL DEFAULT 0,
                contradicted_by INTEGER,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (parent_id) REFERENCES tree_nodes(id)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tree_children (
                parent_id INTEGER NOT NULL,
                child_id INTEGER NOT NULL,
                PRIMARY KEY (parent_id, child_id),
                FOREIGN KEY (parent_id) REFERENCES tree_nodes(id),
                FOREIGN KEY (child_id) REFERENCES tree_nodes(id)
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_nodes_level_time
            ON tree_nodes(level, timestamp)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_nodes_window
            ON tree_nodes(level, window_start, window_end)
        """)
        self.conn.commit()

    def add_leaf(self, content: str, timestamp: float | None = None,
                 metadata: dict | None = None) -> int:
        """Add a raw memory event as a leaf node (level 0)."""
        ts = timestamp or time.time()
        cur = self.conn.execute("""
            INSERT INTO tree_nodes
            (content, timestamp, level, window_start, window_end,
             last_reinforced, metadata)
            VALUES (?, ?, 0, ?, ?, ?, ?)
        """, (content, ts, ts, ts, ts, json.dumps(metadata or {})))
        self.conn.commit()
        return cur.lastrowid

    def get_node(self, node_id: int) -> TreeNode | None:
        row = self.conn.execute(
            "SELECT * FROM tree_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        children = [r[1] for r in self.conn.execute(
            "SELECT parent_id, child_id FROM tree_children WHERE parent_id = ?",
            (node_id,)
        ).fetchall()]
        return TreeNode(
            id=row[0], content=row[1], timestamp=row[2], level=row[3],
            window_start=row[4], window_end=row[5], parent_id=row[6],
            reinforcement_count=row[7], last_reinforced=row[8],
            contradicted_by=row[9], metadata=json.loads(row[10] or '{}'),
            children_ids=children,
        )

    def get_leaves_in_window(self, start: float, end: float,
                             level: int = 0) -> list[TreeNode]:
        rows = self.conn.execute("""
            SELECT id FROM tree_nodes
            WHERE level = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
        """, (level, start, end)).fetchall()
        return [self.get_node(r[0]) for r in rows]

    def get_unconsolidated_leaves(self, level: int = 0) -> list[TreeNode]:
        """Find leaves that haven't been consolidated into a parent yet."""
        rows = self.conn.execute("""
            SELECT id FROM tree_nodes
            WHERE level = ? AND parent_id IS NULL
            ORDER BY timestamp
        """, (level,)).fetchall()
        return [self.get_node(r[0]) for r in rows]

    def create_parent(self, children: list[TreeNode], summary: str,
                      level: int) -> int:
        """Create a consolidated parent node from children."""
        timestamps = [c.timestamp for c in children]
        window_start = min(c.window_start for c in children)
        window_end = max(c.window_end for c in children)
        avg_ts = sum(timestamps) / len(timestamps)
        total_reinforcements = sum(c.reinforcement_count for c in children)

        cur = self.conn.execute("""
            INSERT INTO tree_nodes
            (content, timestamp, level, window_start, window_end,
             reinforcement_count, last_reinforced, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (summary, avg_ts, level, window_start, window_end,
              total_reinforcements, time.time(),
              json.dumps({"child_count": len(children)})))
        parent_id = cur.lastrowid

        for child in children:
            self.conn.execute(
                "UPDATE tree_nodes SET parent_id = ? WHERE id = ?",
                (parent_id, child.id)
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO tree_children (parent_id, child_id) VALUES (?, ?)",
                (parent_id, child.id)
            )

        self.conn.commit()
        return parent_id

    def reinforce(self, node_id: int, amount: int = 1):
        """Reinforce a finding (replication, citation)."""
        self.conn.execute("""
            UPDATE tree_nodes
            SET reinforcement_count = reinforcement_count + ?,
                last_reinforced = ?
            WHERE id = ?
        """, (amount, time.time(), node_id))
        self.conn.commit()

    def contradict(self, node_id: int, by_node_id: int):
        """Mark a finding as contradicted. Resets reinforcement to 0."""
        self.conn.execute("""
            UPDATE tree_nodes
            SET reinforcement_count = 0,
                contradicted_by = ?
            WHERE id = ?
        """, (by_node_id, node_id))
        self.conn.commit()

    def search(self, scope: TimeScope, time_hint: tuple[float, float] | None = None,
               level_range: tuple[int, int] | None = None) -> list[TreeNode]:
        """Retrieve nodes scoped by time and level.

        Args:
            scope: SHORT (levels 0-1), LONG (levels 2+), MIXED (all).
            time_hint: (start, end) timestamp range. None = all time.
            level_range: Override scope with explicit (min_level, max_level).
        """
        if level_range:
            min_level, max_level = level_range
        elif scope == TimeScope.SHORT:
            min_level, max_level = 0, 1
        elif scope == TimeScope.LONG:
            min_level, max_level = 2, 4
        else:
            min_level, max_level = 0, 4

        if time_hint:
            rows = self.conn.execute("""
                SELECT id FROM tree_nodes
                WHERE level >= ? AND level <= ?
                  AND window_end >= ? AND window_start <= ?
                ORDER BY timestamp DESC
            """, (min_level, max_level, time_hint[0], time_hint[1])).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT id FROM tree_nodes
                WHERE level >= ? AND level <= ?
                ORDER BY timestamp DESC
            """, (min_level, max_level)).fetchall()

        return [self.get_node(r[0]) for r in rows]

    def stats(self) -> dict:
        levels = {}
        for level in range(5):
            count = self.conn.execute(
                "SELECT COUNT(*) FROM tree_nodes WHERE level = ?", (level,)
            ).fetchone()[0]
            if count > 0:
                levels[level] = count
        total = sum(levels.values())
        contradicted = self.conn.execute(
            "SELECT COUNT(*) FROM tree_nodes WHERE contradicted_by IS NOT NULL"
        ).fetchone()[0]
        return {"total_nodes": total, "per_level": levels, "contradicted": contradicted}

    def get_forgotten(self, threshold: float = 0.1) -> list[TreeNode]:
        """Return nodes whose robustness has decayed below the forget threshold."""
        rows = self.conn.execute(
            "SELECT id FROM tree_nodes WHERE level = 0"
        ).fetchall()
        forgotten = []
        for (node_id,) in rows:
            node = self.get_node(node_id)
            if node and node.robustness < threshold:
                forgotten.append(node)
        return forgotten

    def update_node(self, node: TreeNode):
        """Persist metadata changes for a node."""
        self.conn.execute(
            "UPDATE tree_nodes SET metadata = ? WHERE id = ?",
            (json.dumps(node.metadata), node.id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
