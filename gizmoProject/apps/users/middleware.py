from django.shortcuts import render
from django.http import JsonResponse


EXEMPT_PREFIXES = (
    '/login/admin/',
    '/logout/',
    '/static/',
    '/api/admin/',   # ALL admin API calls always get through
)


class MaintenanceModeMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.users.models import SiteSettings

        path = request.path_info

        # Always exempt admin API and login
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return self.get_response(request)

        try:
            maintenance = SiteSettings.get().maintenance_mode
            message = SiteSettings.get().maintenance_message
        except Exception:
            return self.get_response(request)

        if not maintenance:
            return self.get_response(request)

        # ── Maintenance is ON ───────────────────────────────────────────────

        user = request.user

        # Admins pass through freely
        if user.is_authenticated and hasattr(user, 'role') and user.role == 'admin':
            return self.get_response(request)

        # Kill the session for any logged-in non-admin
        if user.is_authenticated:
            try:
                request.session.flush()
            except Exception:
                pass

        # JSON response for API calls
        if path.startswith('/api/'):
            return JsonResponse({'ok': False, 'error': 'Platform is under maintenance.'}, status=503)

        # HTML maintenance page for everyone else
        return render(request, 'maintenance.html', {'message': message}, status=503)