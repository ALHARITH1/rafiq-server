import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,os.environ.get('RAFIQ_TEST_APP','/tmp/rafiq-image/app'))
os.environ['HARITH_PBKDF2_ITER']='1000'
from harith.core import Harith
from harith.config import load_settings
from harith.security import create_user,new_api_token
from harith.web import create_app
from starlette.testclient import TestClient
class TempPassword(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.a=Harith(load_settings(env_file=self.t.name+'/none',data_dir=Path(self.t.name)/'data',ai_provider='fake',admin_password='',telegram_bot_token=''))
  self.admin=create_user(self.a.db,'admin-test','fixture-password',role='admin');self.owner=create_user(self.a.db,'owner-test','fixture-password');self.other=create_user(self.a.db,'other-test','fixture-password')
  self.token=new_api_token(self.a.db,self.admin,'test');self.otoken=new_api_token(self.a.db,self.owner,'test');self.c=TestClient(create_app(self.a,manage_lifecycle=False))
 def tearDown(self):self.c.close();self.a.db.close();self.t.cleanup()
 def flag(self):
  r=self.c.patch(f'/api/users/{self.owner}',json={'password_change_required':True},headers={'Authorization':'Bearer '+self.token});self.assertEqual(r.status_code,200)
 def test_login_gate_and_change(self):
  self.flag();r=self.c.post('/api/login',json={'username':'owner-test','password':'fixture-password'});self.assertTrue(r.json()['password_change_required'])
  self.assertEqual(self.c.get('/api/me').status_code,403);self.assertEqual(self.c.get('/',follow_redirects=False).headers['location'],'/change-password')
  self.assertEqual(self.c.get('/change-password').status_code,200);self.assertEqual(self.c.get('/static/change-password.js').status_code,200)
  h={'X-Harith':'1'}
  self.assertEqual(self.c.post('/api/password',json={'current':'bad','new':'different-pass'},headers=h).status_code,403)
  self.assertEqual(self.c.post('/api/password',json={'current':'fixture-password','new':'fixture-password'},headers=h).status_code,400)
  self.assertEqual(self.c.post('/api/password',json={'current':'fixture-password','new':'different-pass'},headers=h).status_code,200)
  self.assertFalse(self.a.db.get_setting(self.owner,'password_change_required'))
  r=self.c.post('/api/login',json={'username':'owner-test','password':'different-pass'});self.assertFalse(r.json()['password_change_required']);self.assertEqual(self.c.get('/api/me').status_code,200)
 def test_api_token_blocked_and_others_unchanged(self):
  self.flag();self.assertEqual(self.c.get('/api/me',headers={'Authorization':'Bearer '+self.otoken}).status_code,403)
  self.assertEqual(self.c.get('/api/me',headers={'Authorization':'Bearer '+self.token}).status_code,200)
  self.assertFalse(self.a.db.get_setting(self.other,'password_change_required',False))
 def test_nonadmin_cannot_flag(self):
  r=self.c.patch(f'/api/users/{self.other}',json={'password_change_required':True},headers={'Authorization':'Bearer '+self.otoken});self.assertEqual(r.status_code,403)
if __name__=='__main__':unittest.main(verbosity=2)
