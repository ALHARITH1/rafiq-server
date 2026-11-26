"""Enforce owner-requested temporary credentials without altering other accounts."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse
from .security import user_for_api_token, user_for_session

KEY = 'password_change_required'

def required(db, uid):
    return bool(db.get_setting(uid, KEY, False))

class TemporaryPasswordGate(BaseHTTPMiddleware):
    def __init__(self, app, harith):
        super().__init__(app)
        self.harith = harith

    async def dispatch(self, request, call_next):
        path = request.url.path
        # Login, the dedicated change form and its assets must remain accessible.
        allowed = path in ('/api/login', '/api/logout', '/api/password', '/change-password') or path.startswith('/static/')
        if not allowed:
            auth = request.headers.get('authorization', '')
            u = user_for_api_token(self.harith.db, auth[7:].strip()) if auth.lower().startswith('bearer ') else user_for_session(self.harith.db, request.cookies.get('harith_session'))
            if u and required(self.harith.db, u['id']):
                if path.startswith('/api/'):
                    return JSONResponse({'error': 'يجب تغيير كلمة المرور المؤقتة أولاً', 'password_change_required': True}, status_code=403)
                return RedirectResponse('/change-password', status_code=303)
        return await call_next(request)
