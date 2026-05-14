from flask import Blueprint

guest_bp = Blueprint("guest", __name__, url_prefix="/guest")
