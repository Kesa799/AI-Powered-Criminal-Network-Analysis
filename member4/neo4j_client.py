import logging
import time
from typing import Dict, Any, List, Optional
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import (
    ConnectionPoolError,
    ServiceUnavailable,
    SessionExpired,
    TransientError,
)

logger = logging.getLogger("graph_system")

# Aura (and every Neo4j Cloud load balancer) drops connections that have been
# idle for a while. A pooled connection that the server closed underneath us
# fails the next query with a "defunct connection" error even though the
# driver, the credentials and the database are all fine. Recycling connections
# before that happens keeps the mirror readable.
MAX_CONNECTION_LIFETIME_S = 300.0

# Errors that mean "the connection died, try again", not "the query is wrong".
_TRANSIENT = (ServiceUnavailable, SessionExpired, ConnectionPoolError, TransientError)

# How many times a query is re-run after a transient connection failure.
MAX_ATTEMPTS = 3


def _retry_delays() -> List[float]:
    return [0.5, 2.0]


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver: Optional[Driver] = None
        self._connected = False
        self._constraints_ready = False

    def connect(self) -> bool:
        try:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=MAX_CONNECTION_LIFETIME_S,
                connection_acquisition_timeout=3.0,
                connection_timeout=3.0,
            )
            self._driver.verify_connectivity()
            self._connected = True
            logger.info(f"Successfully connected to Neo4j at {self.uri}")
            return True
        except Exception as e:
            logger.info(f"Neo4j is not active at {self.uri} ({e}). Operating in high-speed in-memory graph mode.")
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        if self._driver and not self._connected:
            try:
                self._driver.verify_connectivity()
                self._connected = True
            except Exception:
                self._connected = False
        return self._connected

    def close(self):
        if self._driver:
            self._driver.close()
            self._connected = False

    def ensure_constraints(self):
        """Creates baseline constraints and indexes idempotently without hardcoding schema."""
        if not self.is_connected or self._constraints_ready:
            return
        
        queries = [
            "CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE",
            "CREATE CONSTRAINT source_id_unique IF NOT EXISTS FOR (s:Source) REQUIRE s.source_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
            "CREATE INDEX entity_canonical_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type, e.canonical_value)",
            "CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (ev:Event) REQUIRE ev.event_id IS UNIQUE",
            "CREATE INDEX mention_id_idx IF NOT EXISTS FOR (m:Mention) ON (m.mention_id)",
            # Canonical node key used by the graph engine's MERGE statements.
            "CREATE CONSTRAINT entity_node_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
        ]
        with self._driver.session(database=self.database) as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as ex:
                    logger.debug(f"Constraint notice ({q}): {ex}")
        self._constraints_ready = True

    def _run_with_retry(self, action, description: str):
        """Run a Neo4j action, retrying only connection-level failures.

        A query that fails because the pooled connection was closed by the
        server is retried on a fresh connection. A query that fails because of
        its own content (syntax, constraint, timeout) is never retried.
        """
        delays = _retry_delays()
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return action()
            except _TRANSIENT as exc:
                last_exc = exc
                if attempt >= MAX_ATTEMPTS - 1:
                    break
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    f"Transient Neo4j failure during {description}: {exc}. "
                    f"Retrying in {delay}s (attempt {attempt + 2}/{MAX_ATTEMPTS})."
                )
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def execute_write(self, cypher: str, parameters: Optional[Dict[str, Any]] = None):
        if not self.is_connected:
            return None

        def _action():
            with self._driver.session(database=self.database) as session:
                return session.execute_write(lambda tx: list(tx.run(cypher, parameters or {})))

        return self._run_with_retry(_action, "a write")

    def execute_read(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self.is_connected:
            return []

        def _action():
            with self._driver.session(database=self.database) as session:
                res = session.run(cypher, parameters or {})
                return [record.data() for record in res]

        return self._run_with_retry(_action, "a read")

    def get_full_graph(self, limit: int = 2500) -> Dict[str, Any]:
        """Fetch nodes and edges formatted for visualization."""
        if not self.is_connected:
            return {"nodes": [], "edges": []}

        cypher = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT $limit
        """
        nodes_dict = {}
        edges_list = []

        def _fetch():
            local_nodes: Dict[str, Any] = {}
            local_edges: List[Dict[str, Any]] = []
            with self._driver.session(database=self.database) as session:
                result = session.run(cypher, {"limit": limit})
                for record in result:
                    n = record.get("n")
                    r = record.get("r")
                    m = record.get("m")

                    if n:
                        n_id = str(n.element_id if hasattr(n, "element_id") else n.id)
                        labels = list(n.labels)
                        local_nodes[n_id] = {
                            "id": n_id,
                            "labels": labels,
                            "primary_label": labels[0] if labels else "Node",
                            "properties": dict(n.items()),
                            "caption": n.get("canonical_value") or n.get("case_id") or n.get("file_name") or n.get("event_id") or n.get("entity_id") or n_id
                        }
                    if m:
                        m_id = str(m.element_id if hasattr(m, "element_id") else m.id)
                        labels = list(m.labels)
                        local_nodes[m_id] = {
                            "id": m_id,
                            "labels": labels,
                            "primary_label": labels[0] if labels else "Node",
                            "properties": dict(m.items()),
                            "caption": m.get("canonical_value") or m.get("case_id") or m.get("file_name") or m.get("event_id") or m.get("entity_id") or m_id
                        }
                    if r:
                        r_id = str(r.element_id if hasattr(r, "element_id") else r.id)
                        start_id = str(r.start_node.element_id if hasattr(r.start_node, "element_id") else r.start_node.id)
                        end_id = str(r.end_node.element_id if hasattr(r.end_node, "element_id") else r.end_node.id)
                        local_edges.append({
                            "id": r_id,
                            "from": start_id,
                            "to": end_id,
                            "label": r.type,
                            "properties": dict(r.items())
                        })
            return local_nodes, local_edges

        try:
            nodes_dict, edges_list = self._run_with_retry(_fetch, "the full graph fetch")
        except Exception as e:
            logger.error(f"Error fetching full graph from Neo4j: {e}")

        return {
            "nodes": list(nodes_dict.values()),
            "edges": edges_list
        }
