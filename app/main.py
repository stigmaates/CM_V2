from flask import session

from app.core import app, get_db_connection
from app.routes.admin import admin_bp
from app.routes.guest import guest_bp
from app.routes.owner import owner_bp
from app.routes.common import auth_bp, public_bp

from app.routes.admin import clubs, dashboard as admin_dashboard, users  # noqa: F401
from app.routes.owner import club, crm, dashboard, mailing, missions, prize_claims, settings, sync, wheel  # noqa: F401
from app.routes.guest import main  # noqa: F401
from app.routes.common import auth, public  # noqa: F401


@app.context_processor
def inject_header_context():
    """Global context for the owner/admin header."""
    club_name = session.get("club_name")
    club_id = session.get("club_id")

    if club_id and not club_name:
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT name
                    FROM clubs
                    WHERE club_id = %s
                    LIMIT 1
                    """,
                    (club_id,),
                )
                row = cursor.fetchone()
            if row and row.get("name"):
                club_name = row["name"]
                session["club_name"] = club_name
        except Exception:
            club_name = None
        finally:
            if conn:
                conn.close()

    return {
        "header_club_name": club_name,
        "header_user_name": session.get("name"),
        "header_user_login": session.get("login"),
        "is_owner_impersonation": bool(session.get("impersonating_owner")),
        "impersonated_club_name": session.get("impersonated_club_name") or club_name,
    }


app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(owner_bp)
app.register_blueprint(guest_bp)

if __name__ == "__main__":
    app.run()
