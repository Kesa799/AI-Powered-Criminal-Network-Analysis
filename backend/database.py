import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import settings

logger = logging.getLogger("atlas.database")

# Normalize postgres:// to postgresql:// for SQLAlchemy 1.4+ / 2.0+ compatibility
db_url = settings.database_url or "sqlite:///./atlas_fallback.db"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Configure database engine appropriately for SQLite vs PostgreSQL/Supabase
if db_url.startswith("sqlite"):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        connect_args={"connect_timeout": 10}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create all tables in Postgres / SQLite if they do not exist."""
    try:
        import backend.models  # Ensure models are loaded onto Base.metadata
        logger.info(f"Initializing database tables ({'SQLite' if db_url.startswith('sqlite') else 'PostgreSQL'})...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}")
        # Log warning instead of crashing so health check and app remain responsive
        logger.warning("Continuing startup with degraded database connectivity.")
