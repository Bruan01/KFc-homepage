"""
Seed database with initial data when empty.
"""
from app.db import get_db
from app.utils.helpers import now_iso


def seed_if_empty() -> None:
    """Insert a default published product if the products table is empty."""
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count > 0:
            return
        now = now_iso()
        conn.execute(
            """
            INSERT INTO products (slug, name, summary, description, category, tags, announcement, version, changelog, status, created_at, updated_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "kflow-edge-client",
                "KFlow Edge Client",
                "Secure tunneling and endpoint delivery toolkit for distributed teams.",
                "KFlow Edge Client streamlines secure endpoint publishing with low-latency routing and operational visibility.",
                "edge",
                "secure-routing,low-latency,observability",
                "Launch secure tunnels, route edge traffic, and monitor endpoint delivery in one desktop client.",
                "1.0.0",
                "Initial release",
                "published",
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
