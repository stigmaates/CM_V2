from app.core import app
from app.routes.admin import admin_bp
from app.routes.guest import guest_bp
from app.routes.owner import owner_bp
from app.routes.common import auth_bp, public_bp

from app.routes.admin import clubs, dashboard as admin_dashboard, users  # noqa: F401
from app.routes.owner import club, crm, dashboard, mailing, missions, prize_claims, settings, sync, wheel  # noqa: F401
from app.routes.guest import main  # noqa: F401
from app.routes.common import auth, public  # noqa: F401

app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(owner_bp)
app.register_blueprint(guest_bp)

if __name__ == "__main__":
    app.run()
