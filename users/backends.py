from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authentication backend that accepts either email (primary USERNAME_FIELD)
    or the legacy `username` field so tests and external callers using
    username-based login continue to work.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)

        if username is None or password is None:
            return None

        # Try to find by email (primary login field)
        try:
            user = UserModel.objects.get(email=username)
        except UserModel.DoesNotExist:
            # Fallback: try legacy username field
            try:
                user = UserModel.objects.get(username=username)
            except UserModel.DoesNotExist:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
