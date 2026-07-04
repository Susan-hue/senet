from django.urls import path

from accounts.views import (
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    TokenRefreshView,
    VerifyEmailView,
)

urlpatterns = [
    path("register", RegisterView.as_view(), name="auth-register"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="auth-me"),
    path("token/refresh", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("verify-email", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("password-reset", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password-reset/confirm",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
]
