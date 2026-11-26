import hashlib,hmac,json,os,tempfile,sys,unittest
from pathlib import Path
sys.path.insert(0,os.environ.get('RAFIQ_TEST_APP','/app'))
os.environ['HARITH_PBKDF2_ITER']='1000'
from harith.core import Harith
from harith.config import load_settings
from harith.security import create_user,new_api_token
from harith.web import create_app
from starlette.testclient import TestClient

class Connectors(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.a=Harith(load_settings(env_file=self.t.name+'/none',data_dir=Path(self.t.name)/'data',ai_provider='fake',admin_password='',telegram_bot_token=''))
  self.admin=create_user(self.a.db,'admin-test','password123',role='admin');self.owner=create_user(self.a.db,'owner-test','password123');self.other=create_user(self.a.db,'other-test','password123')
  self.token=new_api_token(self.a.db,self.admin,'test');self.other_token=new_api_token(self.a.db,self.other,'test');self.c=TestClient(create_app(self.a,manage_lifecycle=False))
  self.url=f'/api/customer-service/webhooks/meta/{self.owner}'
  for k,v in [('META_VERIFY_TOKEN','fixture-verify'),('META_APP_SECRET','fixture-secret'),('WHATSAPP_PHONE_ID','fixture-phone'),('INSTAGRAM_ACCOUNT_ID','fixture-ig')]:os.environ[f'RAFIQ_CS_{self.owner}_{k}']=v
 def tearDown(self):
  self.c.close();self.a.db.close();self.t.cleanup()
  for k in ['META_VERIFY_TOKEN','META_APP_SECRET','WHATSAPP_PHONE_ID','INSTAGRAM_ACCOUNT_ID']:os.environ.pop(f'RAFIQ_CS_{self.owner}_{k}',None)
 def signed(self,p):
  raw=json.dumps(p).encode();return self.c.post(self.url,content=raw,headers={'x-hub-signature-256':'sha256='+hmac.new(b'fixture-secret',raw,hashlib.sha256).hexdigest()})
 def rows(self):return self.a.db.all('SELECT * FROM cs_messages WHERE user_id=?',(self.owner,))
 def wa(self,phone='fixture-phone'):
  return {'object':'whatsapp_business_account','entry':[{'changes':[{'value':{'metadata':{'phone_number_id':phone},'messages':[{'id':'fixture-message','from':'fixture-customer','type':'text','text':{'body':'رسالة اختبار محلية'}}]}}]}]}
 def test_challenge(self):
  r=self.c.get(self.url,params={'hub.mode':'subscribe','hub.verify_token':'fixture-verify','hub.challenge':'123'});self.assertEqual(r.status_code,200);self.assertEqual(r.text,'123');self.assertEqual(self.c.get(self.url).status_code,403)
 def test_unconfigured(self):
  os.environ.pop(f'RAFIQ_CS_{self.owner}_META_APP_SECRET');self.assertEqual(self.c.get(self.url).status_code,503)
 def test_invalid_signature(self):self.assertEqual(self.c.post(self.url,json=self.wa()).status_code,403);self.assertEqual(len(self.rows()),0)
 def test_wa_idempotent_and_isolated(self):
  self.assertEqual(self.signed(self.wa()).status_code,200);self.signed(self.wa());r=self.rows();self.assertEqual(len(r),1);self.assertEqual(r[0]['reply'],'');self.assertEqual(r[0]['source'],'official');self.assertEqual(r[0]['status'],'open');self.assertEqual(self.a.db.all('SELECT * FROM cs_messages WHERE user_id=?',(self.other,)),[])
 def test_wrong_phone(self):self.signed(self.wa('another-phone'));self.assertEqual(len(self.rows()),0)
 def test_instagram(self):
  p={'object':'instagram','entry':[{'id':'fixture-ig','messaging':[{'sender':{'id':'customer-ig'},'recipient':{'id':'fixture-ig'},'message':{'mid':'fixture-mid','text':'مرحبا'}}]}]};self.assertEqual(self.signed(p).status_code,200);self.assertEqual(self.rows()[0]['channel'],'instagram');p['entry'][0]['messaging'][0]['message']['mid']='echo';p['entry'][0]['messaging'][0]['message']['is_echo']=True;self.signed(p);self.assertEqual(len(self.rows()),1)
 def test_website_owner_scope(self):
  url=f'/api/customer-service/owners/{self.owner}/website';self.assertEqual(self.c.put(url,json={'website_enabled':True},headers={'Authorization':'Bearer '+self.other_token}).status_code,404)
  r=self.c.put(url,json={'website_enabled':True},headers={'Authorization':'Bearer '+self.token});self.assertEqual(r.status_code,200);self.assertFalse(r.json()['auto_reply']);key=r.json()['website_key'];self.assertTrue(key);self.assertFalse(self.a.db.get_setting(self.admin,'cs_website_enabled',False));self.assertFalse(self.a.db.get_setting(self.other,'cs_website_enabled',False))
  self.assertEqual(self.c.put(url,json={'website_enabled':True,'auto_reply':True},headers={'Authorization':'Bearer '+self.token}).status_code,400)
  r=self.c.post('/api/customer-chat/'+key,json={'action':'send','body':'اختبار محلي','request_id':'fixture-web'});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['messages'][0]['reply'],'')
 def test_chat_csp(self):
  r=self.c.get('/customer-chat/fixture');self.assertEqual(r.status_code,200);self.assertNotIn('<script>',r.text);self.assertEqual(self.c.get('/static/customer-chat.js').status_code,200)

if __name__=='__main__':unittest.main(verbosity=2)
