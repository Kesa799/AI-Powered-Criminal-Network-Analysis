import sys
sys.path.insert(0, '.')

from backend.graph_manager import get_graph_engine, neo4j_client
from backend.database import SessionLocal
from backend.models import CaseModel, EvidenceMentionModel, EvidenceItemModel
from backend.pipeline import EvidencePipeline

def resync_clean_graph():
    print("1. Cleaning up invalid USES_VEHICLE / OWNS_VEHICLE edges in Neo4j...")
    # Delete USES_VEHICLE from phone
    neo4j_client.execute_write("MATCH (p:Phone)-[r:USES_VEHICLE]->(v:Vehicle) DELETE r")
    print("   Deleted USES_VEHICLE from Phone")

    # Delete USES_VEHICLE from vehicle to vehicle
    neo4j_client.execute_write("MATCH (v1:Vehicle)-[r:USES_VEHICLE]->(v2:Vehicle) DELETE r")
    print("   Deleted USES_VEHICLE between Vehicles")

    # Delete USES_VEHICLE or OWNS_VEHICLE from police officers
    neo4j_client.execute_write("""
        MATCH (p:Person)-[r]->(v:Vehicle)
        WHERE (r:USES_VEHICLE OR r:OWNS_VEHICLE) AND (toLower(p.id) CONTAINS 'inspector' OR toLower(p.id) CONTAINS 'officer' OR toLower(p.id) CONTAINS 'si_')
        DELETE r
    """)
    print("   Deleted vehicle links from Police Officers")

    # Delete USES_VEHICLE on background ANPR passing vehicles (TS00ZZ*)
    neo4j_client.execute_write("""
        MATCH (a)-[r:USES_VEHICLE]->(v:Vehicle)
        WHERE v.id CONTAINS 'ZZ'
        DELETE r
    """)
    print("   Deleted USES_VEHICLE edges to ZZ background vehicles")

    print("\n2. Rebuilding in-memory KnowledgeGraphEngine and re-running clean graph completion...")
    engine = get_graph_engine()
    engine.clear()
    engine.load_from_neo4j()

    db = SessionLocal()
    cases = db.query(CaseModel).all()
    for c in cases:
        EvidencePipeline._complete_case_graph(c.case_id, engine)
    
    print(f"3. Syncing clean graph to Neo4j ({len(engine.nodes)} nodes, {len(engine.edges)} edges)...")
    engine.sync_to_neo4j()
    print("Done! Clean graph synchronized successfully.")

if __name__ == '__main__':
    resync_clean_graph()
