from flask import render_template

from app.core import owner_required
from app.routes.owner import owner_bp
from app.services.training import list_training_videos


@owner_bp.get("/training")
@owner_required
def training():
    return render_template("owner/training.html", videos=list_training_videos())
