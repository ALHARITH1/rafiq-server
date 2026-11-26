from pathlib import Path
p=Path('/app/harith/web.py');s=p.read_text()
def patch(old,new):
 global s
 assert s.count(old)==1,old[:100]
 s=s.replace(old,new)
patch('        resp = J({"ok": True, "user": _public_user(u)})','        from .temporary_password import required\n        resp = J({"ok": True, "user": _public_user(u), "password_change_required": required(app.db, u["id"])})')
patch('        app.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(b["new"]), u["id"]))','        if b["new"] == b.get("current"):\n            raise HTTPError(400, "اختر كلمة مرور مختلفة عن المؤقتة")\n        app.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(b["new"]), u["id"]))\n        app.db.set_setting(u["id"], "password_change_required", False)')
patch('            if len(b["password"]) < 8:', '            minimum = 4 if b.get("password_change_required") is True else 8\n            if len(b["password"]) < minimum:')
patch('        if "is_test" in b:','        if "password_change_required" in b:\n            app.db.set_setting(uid, "password_change_required", bool(b["password_change_required"]))\n            if b["password_change_required"]:\n                app.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))\n        if "is_test" in b:')
patch('    async def password_change(req: Request, u: dict):', '    async def password_change_page(req: Request):\n        return FileResponse(STATIC / \"change-password.html\")\n\n    async def password_change(req: Request, u: dict):')
patch('    web = Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)], lifespan=lifespan)','    from .temporary_password import TemporaryPasswordGate\n    web = Starlette(routes=routes, middleware=[Middleware(SecurityHeaders), Middleware(TemporaryPasswordGate, harith=app)], lifespan=lifespan)')
patch('        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),','        R("/change-password", password_change_page, auth=False),\n        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),')
p.write_text(s)
p=Path('/app/harith/static/app.js');s=p.read_text();needle="  if (!r.ok) { const m = (data && data.error)"
assert s.count(needle)==1
s=s.replace(needle,"  if (data && data.password_change_required) { location.replace('/change-password'); throw new Error('password_change_required'); }\n"+needle)
p.write_text(s)
# Cache version includes the new login flow.
p=Path('/app/harith/static/sw.js');s=p.read_text();s=s.replace('rafiq-shell-v5-customer-service','rafiq-shell-v6-temp-password');p.write_text(s)
print('temporary-password integration applied')
