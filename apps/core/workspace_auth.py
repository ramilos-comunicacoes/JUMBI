import hashlib
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.core.cache import cache


def login_key(email):
    return "login:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or kwargs.get("email") or "").strip().lower()
        if not email or password is None:
            return None
        key = login_key(email)
        if cache.get(key, 0) >= 10:
            return None
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            cache.delete(key)
            return user
        if not user:
            User().set_password(password)
        cache.set(key, cache.get(key, 0) + 1, 15 * 60)
        return None
