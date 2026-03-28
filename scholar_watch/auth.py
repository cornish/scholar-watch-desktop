"""Authentication module using Flask-Login and bcrypt."""

import bcrypt
from flask_login import LoginManager, UserMixin

from .database import get_session
from .models import User

login_manager = LoginManager()
login_manager.login_view = "dashboard.login"
login_manager.login_message_category = "info"


class FlaskUser(UserMixin):
    """Wrapper to make SQLAlchemy User compatible with Flask-Login."""

    def __init__(self, user: User):
        self.id = user.id
        self.email = user.email
        self.display_name = user.display_name
        self.user = user


@login_manager.user_loader
def load_user(user_id: str) -> FlaskUser | None:
    session = get_session()
    try:
        user = session.get(User, int(user_id))
        if user and user.is_active:
            return FlaskUser(user)
        return None
    finally:
        session.close()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
