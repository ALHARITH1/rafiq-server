"""Additive, no-cost customer inbox. No paid AI calls or unofficial social login.
External channel connectors remain disconnected until credentials and permissions exist.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
from datetime import timedelta
from starlette.responses import JSONResponse, FileResponse
from .db import now_iso, utcnow, iso
from .timeutil import local_now, parse_local
from .security import RateLimiter

CHANNELS = {
    'website': ('الموقع', 'صفحة محادثة يمكن تفعيلها بعد اعتماد الأسئلة والإجابات.'),
    'whatsapp': ('واتساب', 'غير مربوط. يحتاج حساب WhatsApp Business Platform وصلاحياته. الردود المجانية مقيدة بسياسة المنصة؛ لا إرسال مدفوع.'),
    'instagram': ('إنستغرام', 'غير مربوط. يحتاج حساباً احترافياً وتطبيق Meta وصلاحية الرسائل والمراجعة عند لزومها.'),
    'tiktok': ('تيك توك', 'غير مربوط. يحتاج قبول الوصول إلى Business Messaging API وتفويض حساب الأعمال.'),
}


def init_schema(db):
    # Separate tables, never alter or drop existing tables or data.
    statements = [
        """CREATE TABLE IF NOT EXISTS cs_messages(id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        channel TEXT NOT NULL, customer TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
        reply TEXT NOT NULL DEFAULT '', reply_kind TEXT NOT NULL DEFAULT 'none',
        status TEXT NOT NULL DEFAULT 'open', source TEXT NOT NULL DEFAULT 'manual',
        external_id TEXT, session_hash TEXT, task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id,channel,external_id))""",
        "CREATE INDEX IF NOT EXISTS cs_messages_user ON cs_messages(user_id,id)",
        """CREATE TABLE IF NOT EXISTS cs_answers(id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        question TEXT NOT NULL, normalized TEXT NOT NULL, answer TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
        UNIQUE(user_id,normalized))""",
        """CREATE TABLE IF NOT EXISTS cs_reports(id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        report_day TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(user_id,report_day))""",
    ]
    with db.tx():
        for s in statements:
            db.execute(s)


def normalized(s):
    s = re.sub('[\u064b-\u065f\u0670ـ]', '', str(s).lower())
    s = re.sub('[أإآ]', 'ا', s)
    return re.sub(r'[^\w\s]', ' ', s).strip()


def match_answer(db, uid, text):
    n = ' '.join(normalized(text).split())
    row = db.one('SELECT answer FROM cs_answers WHERE user_id=? AND normalized=? AND enabled=1', (uid, n))
    return row['answer'] if row else ''


def config(db, uid):
    return {'report_enabled': bool(db.get_setting(uid, 'cs_report_enabled', False)),
            'report_time': '08:00', 'timezone': 'Asia/Riyadh',
            'website_enabled': bool(db.get_setting(uid, 'cs_website_enabled', False)),
            'website_key': db.get_setting(uid, 'cs_website_key', ''),
            'auto_reply': bool(db.get_setting(uid, 'cs_auto_reply', False)),
            'free_only': True, 'ai_enabled': False}


def channel_state(db, uid):
    c = config(db, uid)
    return [{'id': key, 'name': value[0], 'connected': key == 'website' and c['website_enabled'],
             'detail': value[1]} for key, value in CHANNELS.items()]


def summary(db, uid):
    start = iso(utcnow() - timedelta(hours=24))
    rows = db.all('SELECT channel,status,reply_kind,source FROM cs_messages WHERE user_id=? AND created_at>=?', (uid, start))
    totals = {'received': len(rows), 'automatic': sum(r['reply_kind'] == 'automatic' for r in rows),
              'open': sum(r['status'] == 'open' for r in rows),
              'manual': sum(r['source'] == 'manual' for r in rows)}
    lines = ['تقرير خدمة العملاء | ' + local_now('Asia/Riyadh').strftime('%Y-%m-%d %H:%M'),
             'الفترة: آخر 24 ساعة. الأرقام تخص الرسائل المحفوظة في هذا الصندوق فقط.',
             f"الرسائل المسجلة: {totals['received']} | الردود التلقائية: {totals['automatic']} | بانتظار المتابعة: {totals['open']}."]
    for c in channel_state(db, uid):
        n = sum(r['channel'] == c['id'] for r in rows)
        lines.append(c['name'] + ': ' + (f'مفعّل، {n} رسالة.' if c['connected'] else f'غير مربوط؛ {n} رسالة مدخلة يدوياً، وليس قياساً لحساب القناة.'))
    follow = db.all("SELECT id,channel,customer,body,task_id FROM cs_messages WHERE user_id=? AND status='open' ORDER BY id LIMIT 10", (uid,))
    if follow:
        lines.append('المتابعة المطلوبة:')
        lines += [f"#{r['id']} | {CHANNELS[r['channel']][0]} | {r['customer'] or 'عميل'} | {r['body'][:100]}" for r in follow]
    else:
        lines.append('لا توجد رسائل مفتوحة في الصندوق. هذا لا يعني عدم وجود رسائل في القنوات غير المربوطة.')
    return {'totals': totals, 'channels': channel_state(db, uid), 'content': '\n'.join(lines)}


def ensure_jobs(app):
    for r in app.db.all("SELECT s.user_id FROM settings_kv s JOIN users u ON u.id=s.user_id WHERE s.key='cs_report_enabled' AND s.value='true' AND u.disabled=0"):
        uid = r['user_id']
        loc = local_now('Asia/Riyadh')
        day = loc.replace(hour=8, minute=0, second=0, microsecond=0)
        if day <= loc:
            day += timedelta(days=1)
        at = parse_local(day.isoformat(), 'Asia/Riyadh')
        app.scheduler.enqueue(uid, 'customer_report', {}, at,
                              dedupe_key=f"customer_report:{uid}:{day.strftime('%Y-%m-%d')}", max_attempts=3)


async def report_job(app, job, payload):
    uid = job['user_id']
    if not app.db.get_setting(uid, 'cs_report_enabled', False):
        return 'تقرير خدمة العملاء موقوف'
    if app.is_paused(uid):
        from .scheduler import RetryLater
        raise RetryLater('التنفيذ موقوف')
    day = local_now('Asia/Riyadh').strftime('%Y-%m-%d')
    data = summary(app.db, uid)
    # Persist before delivery; notification dedupe makes retry safe.
    app.db.execute('INSERT INTO cs_reports(user_id,report_day,content,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,report_day) DO NOTHING',
                   (uid, day, data['content'], now_iso()))
    saved = app.db.one('SELECT content FROM cs_reports WHERE user_id=? AND report_day=?', (uid, day))
    await app.notify(uid, saved['content'], dedupe=f'customer_report:{uid}:{day}', kind='notice')
    return 'حُفظ تقرير خدمة العملاء في رفيق'


def register(app):
    init_schema(app.db)
    app.scheduler.register('customer_report', lambda job, p: report_job(app, job, p))


def routes(app, R, HTTPError, STATIC):
    db = app.db
    public_limit = RateLimiter(15, 60)
    J = JSONResponse

    async def read_body(req):
        raw = await req.body()
        if len(raw) > 16000:
            raise HTTPError(413, 'الطلب كبير جداً')
        b = json.loads(raw) if raw else {}
        if not isinstance(b, dict):
            raise HTTPError(400, 'صيغة الطلب غير صحيحة')
        return b

    def text(b, key, limit, required=False):
        v = b.get(key, '')
        if not isinstance(v, str) or len(v) > limit or (required and not v.strip()):
            raise HTTPError(400, 'قيمة غير صحيحة: ' + key)
        return v.strip()

    async def overview(req, u):
        uid = u['id']
        shared = []
        for entry in db.all("SELECT user_id,value FROM settings_kv WHERE key='cs_report_readers' AND user_id<>?", (uid,)):
            if uid in json.loads(entry['value']):
                owner = db.one('SELECT display_name FROM users WHERE id=? AND disabled=0', (entry['user_id'],))
                if owner:
                    shared.append({'owner_id': entry['user_id'], 'owner_name': owner['display_name'],
                                   'reports': db.all('SELECT report_day,content,created_at FROM cs_reports WHERE user_id=? ORDER BY id DESC LIMIT 7', (entry['user_id'],))})
        return J({'config': config(db, uid), 'shared_reports': shared, **summary(db, uid),
                  'answers': db.all('SELECT id,question,answer,enabled FROM cs_answers WHERE user_id=? ORDER BY id DESC', (uid,)),
                  'messages': db.all('SELECT id,channel,customer,body,reply,reply_kind,status,source,task_id,created_at FROM cs_messages WHERE user_id=? ORDER BY id DESC LIMIT 100', (uid,)),
                  'reports': db.all('SELECT report_day,content,created_at FROM cs_reports WHERE user_id=? ORDER BY id DESC LIMIT 7', (uid,))})

    async def settings(req, u):
        b = await read_body(req)
        for k in ('report_enabled', 'website_enabled', 'auto_reply'):
            if k in b and not isinstance(b[k], bool):
                raise HTTPError(400, 'قيمة الإعداد يجب أن تكون منطقية')
        with db.tx():
            for k in ('report_enabled', 'website_enabled', 'auto_reply'):
                if k in b:
                    db.set_setting(u['id'], 'cs_' + k, b[k])
            if b.get('website_enabled') and not db.get_setting(u['id'], 'cs_website_key'):
                db.set_setting(u['id'], 'cs_website_key', secrets.token_urlsafe(24))
        ensure_jobs(app)
        return J({'ok': True, 'config': config(db, u['id'])})

    async def answers(req, u):
        b = await read_body(req)
        q, a = text(b, 'question', 500, True), text(b, 'answer', 2000, True)
        n = ' '.join(normalized(q).split())
        if not n:
            raise HTTPError(400, 'السؤال فارغ')
        with db.tx():
            if not db.one('SELECT id FROM cs_answers WHERE user_id=? AND normalized=?', (u['id'], n)):
                count = db.one('SELECT COUNT(*) n FROM cs_answers WHERE user_id=?', (u['id'],))['n']
                if count >= 200:
                    raise HTTPError(400, 'الحد الأقصى 200 إجابة')
            db.execute('INSERT INTO cs_answers(user_id,question,normalized,answer,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,normalized) DO UPDATE SET question=excluded.question,answer=excluded.answer,enabled=1', (u['id'], q, n, a, now_iso()))
        return J({'ok': True})

    async def disable_answer(req, u):
        db.execute('UPDATE cs_answers SET enabled=0 WHERE id=? AND user_id=?', (req.path_params['id'], u['id']))
        return J({'ok': True})

    async def add_message(req, u):
        b = await read_body(req)
        ch = text(b, 'channel', 30, True)
        if ch not in CHANNELS:
            raise HTTPError(400, 'قناة غير معروفة')
        body = text(b, 'body', 4000, True)
        cust = text(b, 'customer', 120)
        reply = match_answer(db, u['id'], body)
        now = now_iso()
        mid = db.insert('INSERT INTO cs_messages(user_id,channel,customer,body,reply,reply_kind,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)', (u['id'], ch, cust, body, reply, 'draft' if reply else 'none', 'manual', now, now))
        return J({'ok': True, 'id': mid, 'reply': reply, 'sent': False})

    async def message_update(req, u):
        b = await read_body(req)
        mid = req.path_params['id']
        row = db.one('SELECT * FROM cs_messages WHERE id=? AND user_id=?', (mid, u['id']))
        if not row:
            raise HTTPError(404, 'الرسالة غير موجودة')
        state = b.get('status', row['status'])
        if state not in ('open', 'done'):
            raise HTTPError(400, 'حالة غير صحيحة')
        reply = text(b, 'reply', 2000) if 'reply' in b else row['reply']
        # All social entries are manual, so never pretend a reply reached a social account.
        deliver = b.get('deliver', False)
        if not isinstance(deliver, bool):
            raise HTTPError(400, 'قيمة إرسال غير صحيحة')
        if deliver and (row['source'] != 'website' or not reply or app.is_paused(u['id'])):
            raise HTTPError(400, 'لا يمكن الإرسال: هذه رسالة يدوية أو التنفيذ موقوف. يمكنك حفظ مسودة فقط.')
        kind = 'owner' if deliver else 'draft' if 'reply' in b else row['reply_kind']
        db.execute('UPDATE cs_messages SET reply=?,reply_kind=?,status=?,updated_at=? WHERE id=? AND user_id=?', (reply, kind, state, now_iso(), mid, u['id']))
        return J({'ok': True, 'sent': deliver})

    async def make_task(req, u):
        mid = req.path_params['id']
        with db.tx():
            row = db.one('SELECT * FROM cs_messages WHERE id=? AND user_id=?', (mid, u['id']))
            if not row:
                raise HTTPError(404, 'الرسالة غير موجودة')
            if row['task_id']:
                return J({'ok': True, 'task_id': row['task_id'], 'existing': True})
            now = now_iso()
            tid = db.insert("INSERT INTO tasks(user_id,title,notes,status,priority,source,created_at,updated_at) VALUES(?,?,?,'open','normal','customer-service',?,?)", (u['id'], 'متابعة عميل: ' + (row['customer'] or CHANNELS[row['channel']][0]) + ' - ' + row['body'][:120], f"رسالة خدمة العملاء #{mid} | {row['channel']}\n{row['body']}", now, now))
            db.execute('UPDATE cs_messages SET task_id=?,updated_at=? WHERE id=? AND user_id=?', (tid, now, mid, u['id']))
        return J({'ok': True, 'task_id': tid})

    async def preview(req, u):
        return J(summary(db, u['id']))

    async def shared_reports(req, u):
        owner = req.path_params['owner']
        readers = db.get_setting(owner, 'cs_report_readers', [])
        if u['id'] != owner and u['id'] not in readers:
            raise HTTPError(404, 'التقرير غير متاح لهذا الحساب')
        return J({'owner_id': owner, 'timezone': 'Asia/Riyadh', 'scheduled_time': '08:00',
                  'reports': db.all('SELECT report_day,content,created_at FROM cs_reports WHERE user_id=? ORDER BY id DESC LIMIT 7', (owner,))})

    async def public_page(req):
        return FileResponse(STATIC / 'customer-chat.html')

    async def public_message(req):
        key = req.path_params['key']
        owner = db.one("SELECT s.user_id FROM settings_kv s JOIN users u ON u.id=s.user_id WHERE s.key='cs_website_key' AND s.value=? AND u.disabled=0", (json.dumps(key),))
        if not owner or not db.get_setting(owner['user_id'], 'cs_website_enabled', False):
            raise HTTPError(404, 'المحادثة غير مفعلة')
        uid = owner['user_id']
        if app.is_paused(uid):
            raise HTTPError(503, 'المحادثة موقوفة مؤقتاً')
        ip = req.client.host if req.client else '?'
        if not public_limit.allow('ip:' + ip) or not public_limit.allow('owner:' + str(uid)):
            raise HTTPError(429, 'رسائل كثيرة، انتظر دقيقة')
        b = await read_body(req)
        session = text(b, 'session', 100)
        if session and not re.fullmatch('[A-Za-z0-9_-]{43}', session):
            raise HTTPError(400, 'جلسة غير صحيحة')
        if not session:
            session = secrets.token_urlsafe(32)
        sh = hashlib.sha256(session.encode()).hexdigest()
        action = b.get('action', 'send')
        if action == 'send':
            msg = text(b, 'body', 4000, True)
            # Caller-generated idempotency ID only dedupes within this session.
            request_id = text(b, 'request_id', 80, True)
            ext = sh + ':' + request_id
            row = db.one('SELECT id FROM cs_messages WHERE user_id=? AND channel=? AND external_id=?', (uid, 'website', ext))
            if not row:
                reply = match_answer(db, uid, msg) if db.get_setting(uid, 'cs_auto_reply', False) else ''
                now = now_iso()
                db.execute("INSERT OR IGNORE INTO cs_messages(user_id,channel,customer,body,reply,reply_kind,status,source,external_id,session_hash,created_at,updated_at) VALUES(?,'website','زائر الموقع',?,?,?,?,'website',?,?,?,?)", (uid, msg, reply, 'automatic' if reply else 'none', 'done' if reply else 'open', ext, sh, now, now))
        elif action != 'read':
            raise HTTPError(400, 'عملية غير صحيحة')
        # Never return drafts to visitors. A bearer session only sees its own messages.
        messages = db.all("SELECT id,body,CASE WHEN reply_kind IN ('automatic','owner') THEN reply ELSE '' END reply,created_at FROM cs_messages WHERE user_id=? AND session_hash=? ORDER BY id DESC LIMIT 40", (uid, sh))
        return J({'session': session, 'messages': list(reversed(messages))}, headers={'Cache-Control': 'no-store'})

    return [R('/api/customer-service', overview),
            R('/api/customer-service/settings', settings, ['PUT']),
            R('/api/customer-service/answers', answers, ['POST']),
            R('/api/customer-service/answers/{id:int}/disable', disable_answer, ['POST']),
            R('/api/customer-service/messages', add_message, ['POST']),
            R('/api/customer-service/messages/{id:int}', message_update, ['PATCH']),
            R('/api/customer-service/messages/{id:int}/task', make_task, ['POST']),
            R('/api/customer-service/report-preview', preview),
            R('/api/customer-service/reports/{owner:int}', shared_reports),
            R('/customer-chat/{key:str}', public_page, auth=False),
            R('/api/customer-chat/{key:str}', public_message, ['POST'], auth=False)]
