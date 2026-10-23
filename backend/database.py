import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import settings

logger = logging.getLogger("atlas.database")

def create_app_engine(raw_url: str):
    url = raw_url.strip() if raw_url else ""
    if not url:
        url = "sqlite:///./atlas_fallback.db"

    # Normalize postgres:// to postgresql:// for SQLAlchemy 1.4+ / 2.0+ compatibility
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    # If it's a PostgreSQL URL without explicit driver:
    if url.startswith("postgresql://") and "+" not in url.split("://")[0]:
        try:
            import psycopg  # noqa: F401
        except ImportError:
            # Fallback to psycopg2 binary driver
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    else:
        try:
            return create_engine(
                url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 10}
            )
        except Exception as e:
            logger.error(f"Could not initialize PostgreSQL engine ({e}). Falling back to local SQLite.")
            return create_engine("sqlite:///./atlas_fallback.db", connect_args={"check_same_thread": False})

engine = create_app_engine(settings.database_url)

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
        logger.info("Initializing database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}")
        logger.warning("Continuing startup with degraded database connectivity.")
