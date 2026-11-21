"""Restore customer-service integration into the base image code (idempotent-ish, assert-guarded)."""
from pathlib import Path

# core.py: register module on app boot
p = Path('/app/harith/core.py'); s = p.read_text()
needle = '        self.bootstrap_admin()'
assert s.count(needle) == 1
p.write_text(s.replace(needle, needle + '\n        from .customer_service import register as register_customer_service\n        register_customer_service(self)'))

# scheduler.py: re-enqueue daily 08:00 report jobs
p = Path('/app/harith/scheduler.py'); s = p.read_text()
needle = '        self.repair_chains()'
assert s.count(needle) == 1
p.write_text(s.replace(needle, needle + '\n        from .customer_service import ensure_jobs as ensure_customer_jobs\n        ensure_customer_jobs(self.app)'))

# web.py: mount routes, ship static, include cs tables in export/wipe, wipe cs settings on delete
p = Path('/app/harith/web.py'); s = p.read_text()
needle = '    @asynccontextmanager\n    async def lifespan(_)'
assert s.count(needle) == 1
s = s.replace(needle, '    from .customer_service import routes as customer_service_routes\n    routes[0:0] = customer_service_routes(app, R, HTTPError, STATIC)\n\n' + needle)
s = s.replace('("app.js", "biz.js", "pm.js", "style.css", "download.js")', '("app.js", "biz.js", "pm.js", "style.css", "download.js", "customer-service.js")')
needle = '                  "meetings", "audit"):'
assert s.count(needle) == 1
s = s.replace(needle, '                  "meetings", "audit", "cs_messages", "cs_answers", "cs_reports"):')
needle = '                  "approvals", "operations", "runs", "usage"):'
assert s.count(needle) == 1
s = s.replace(needle, '                  "approvals", "operations", "runs", "usage", "cs_messages", "cs_answers", "cs_reports"):')
needle = '        app.scheduler.cancel_jobs(uid)\n        return n'
assert s.count(needle) == 1
s = s.replace(needle, "        app.db.execute(\"DELETE FROM settings_kv WHERE user_id=? AND key GLOB 'cs_*'\", (uid,))\n" + needle)
p.write_text(s)

# sw.js: cache bump + precache
p = Path('/app/harith/static/sw.js'); s = p.read_text()
assert "const CACHE = 'rafiq-shell-v4';" in s
s = s.replace("const CACHE = 'rafiq-shell-v4';", "const CACHE = 'rafiq-shell-v5-customer-service';").replace("'/static/pm.js',", "'/static/pm.js', '/static/customer-service.js',")
p.write_text(s)

# index.html: load the view script
p = Path('/app/harith/static/index.html'); s = p.read_text()
needle = '<script src="/static/app.js"></script>'
assert s.count(needle) == 1
p.write_text(s.replace(needle, '<script src="/static/customer-service.js"></script>\n' + needle))
print('cs integration applied')
