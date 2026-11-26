"""Official inbound Meta webhook adapter. No sends, paid calls, or AI calls.
Configuration is deployment-only, never returned by an API.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from starlette.responses import JSONResponse, PlainTextResponse
from .db import now_iso


def routes(app, R, HTTPError):
    db = app.db

    def setting(owner, name):
        return os.environ.get(f'RAFIQ_CS_{owner}_{name}', '')

    async def website_owner(req, u):
        owner = req.path_params['owner']
        if u['id'] != owner and u['role'] != 'admin':
            raise HTTPError(404, 'الحساب غير متاح')
        row = db.one('SELECT id FROM users WHERE id=? AND disabled=0', (owner,))
        if not row:
            raise HTTPError(404, 'الحساب غير متاح')
        if req.method == 'GET':
            return JSONResponse({'owner_id': owner, 'website_enabled': bool(db.get_setting(owner, 'cs_website_enabled', False)),
                                 'website_key': db.get_setting(owner, 'cs_website_key', ''),
                                 'auto_reply': bool(db.get_setting(owner, 'cs_auto_reply', False))})
        b = await req.json()
        if not isinstance(b, dict) or set(b) != {'website_enabled'} or not isinstance(b['website_enabled'], bool):
            raise HTTPError(400, 'يُسمح بتغيير استقبال الموقع فقط')
        import secrets
        with db.tx():
            db.set_setting(owner, 'cs_website_enabled', b['website_enabled'])
            if b['website_enabled'] and not db.get_setting(owner, 'cs_website_key', ''):
                db.set_setting(owner, 'cs_website_key', secrets.token_urlsafe(24))
            # This endpoint never changes automatic replies or any other account.
        return JSONResponse({'owner_id': owner, 'website_enabled': b['website_enabled'],
                             'website_key': db.get_setting(owner, 'cs_website_key', ''),
                             'auto_reply': bool(db.get_setting(owner, 'cs_auto_reply', False))})

    async def webhook(req):
        owner = req.path_params['owner']
        user = db.one('SELECT id FROM users WHERE id=? AND disabled=0', (owner,))
        if not user:
            raise HTTPError(404, 'غير متاح')
        verify, secret = setting(owner, 'META_VERIFY_TOKEN'), setting(owner, 'META_APP_SECRET')
        if not verify or not secret:
            raise HTTPError(503, 'لم يكتمل إعداد الربط الرسمي')
        if req.method == 'GET':
            q = req.query_params
            if q.get('hub.mode') != 'subscribe' or not hmac.compare_digest(q.get('hub.verify_token', ''), verify):
                raise HTTPError(403, 'التحقق مرفوض')
            challenge = q.get('hub.challenge', '')
            if len(challenge) > 512:
                raise HTTPError(400, 'طلب غير صالح')
            return PlainTextResponse(challenge)
        raw = await req.body()
        if len(raw) > 262144:
            raise HTTPError(413, 'الطلب كبير جداً')
        expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(req.headers.get('x-hub-signature-256', ''), expected):
            raise HTTPError(403, 'توقيع غير صالح')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, 'طلب غير صالح')
        if not isinstance(payload, dict) or not isinstance(payload.get('entry', []), list):
            raise HTTPError(400, 'طلب غير صالح')
        count = 0
        now = now_iso()
        def save(channel, external, customer, body):
            nonlocal count
            if not all(isinstance(v, str) and v for v in (external, customer, body)):
                return
            if len(external) > 512 or len(customer) > 120:
                return
            with db.tx():
                before = db.one('SELECT id FROM cs_messages WHERE user_id=? AND channel=? AND external_id=?', (owner, channel, external))
                if before:
                    return
                db.execute("INSERT OR IGNORE INTO cs_messages(user_id,channel,customer,body,reply_kind,status,source,external_id,created_at,updated_at) VALUES(?,?,?,?,'none','open','official',?,?,?)",
                           (owner, channel, customer, body[:4000], external, now, now))
                count += 1
        if payload.get('object') == 'whatsapp_business_account':
            phone = setting(owner, 'WHATSAPP_PHONE_ID')
            if phone:
                for entry in payload.get('entry', []):
                    if not isinstance(entry, dict): continue
                    for change in entry.get('changes', []):
                        if not isinstance(change, dict): continue
                        value = change.get('value', {})
                        if not isinstance(value, dict) or value.get('metadata', {}).get('phone_number_id') != phone: continue
                        for m in value.get('messages', []):
                            if not isinstance(m, dict): continue
                            body = m.get('text', {}).get('body', '') if m.get('type') == 'text' else '[مرفق من واتساب: ' + str(m.get('type', 'unknown'))[:40] + ']'
                            save('whatsapp', m.get('id'), m.get('from'), body)
        elif payload.get('object') == 'instagram':
            account = setting(owner, 'INSTAGRAM_ACCOUNT_ID')
            if account:
                for entry in payload.get('entry', []):
                    if not isinstance(entry, dict) or str(entry.get('id')) != account: continue
                    for event in entry.get('messaging', []):
                        if not isinstance(event, dict): continue
                        msg = event.get('message', {})
                        if not isinstance(msg, dict) or msg.get('is_echo'): continue
                        if str(event.get('recipient', {}).get('id')) != account: continue
                        body = msg.get('text') or ('[مرفق من إنستغرام]' if msg.get('attachments') else '')
                        save('instagram', msg.get('mid'), event.get('sender', {}).get('id'), body)
        if count:
            # Receipt is evidence of inbound delivery, not permission to send.
            db.set_setting(owner, 'cs_official_last_received', now)
        return JSONResponse({'received': True})

    return [R('/api/customer-service/owners/{owner:int}/website', website_owner, ['GET', 'PUT']),
            R('/api/customer-service/webhooks/meta/{owner:int}', webhook, ['GET', 'POST'], auth=False)]
