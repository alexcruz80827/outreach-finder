import json
import unittest
import app
from test_app import DatabaseCase, prospect

class WorkspaceTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        app.import_prospects(self.db, {'prospects':[prospect()]})

    def request(self, method, path, payload=None, origin='http://127.0.0.1:3018'):
        code, _, raw = app.handle_request(self.db, method, path, {'Host':'127.0.0.1:3018','Origin':origin,'Content-Type':'application/json'}, json.dumps(payload).encode() if payload is not None else b'', 3018)
        return code, json.loads(raw)

    def test_campaign_creation_membership_is_idempotent_and_validated(self):
        code, result = self.request('POST','/api/campaigns',{'id':'research','name':'Research cohort'})
        self.assertEqual(code,200)
        self.assertEqual(result['campaign']['name'],'Research cohort')
        for _ in range(2):
            self.assertEqual(self.request('POST','/api/campaigns/research/members',{'prospect_id':'test-owner','assigned':True})[0],200)
        campaigns=self.request('GET','/api/campaigns')[1]['campaigns']
        self.assertEqual(campaigns[0]['members'],['test-owner'])
        self.assertEqual(self.request('POST','/api/campaigns/research/members',{'prospect_id':'missing','assigned':True})[0],404)
        self.assertEqual(self.request('POST','/api/campaigns',{'id':'../bad','name':'Bad'})[0],400)
        self.assertEqual(self.request('POST','/api/campaigns',{'id':'research','name':'Different'})[0],400)
        self.assertEqual(self.request('POST','/api/campaigns',{'id':'no','name':'No'},origin='http://evil.test')[0],403)
        self.assertEqual(self.request('POST','/api/campaigns/research/members',{'prospect_id':'test-owner','assigned':False})[0],200)
        self.assertEqual(self.request('GET','/api/campaigns')[1]['campaigns'][0]['members'],[])

    def test_metadata_events_suppression_and_reimport(self):
        path='/api/prospects/test-owner/outreach'
        self.assertEqual(self.request('GET',path)[1]['metadata'],{'draft':'','follow_up_at':None})
        self.assertEqual(self.request('POST',path,{'draft':'A real editable draft','follow_up_at':'2026-10-26T12:00:00-04:00'})[0],200)
        event={'id':'event-1','prospect_id':'test-owner','campaign_id':None,'kind':'contacted','occurred_at':'2026-10-26T12:00:00Z','note':'Manually confirmed'}
        for _ in range(2): self.assertEqual(self.request('POST','/api/events',event)[0],200)
        self.assertEqual(len(self.request('GET','/api/events')[1]['events']),1)
        self.assertEqual(self.request('POST','/api/events',{**event,'note':'conflict'})[0],400)
        for bad in ({'occurred_at':'2026-10-26'},{'kind':'opened'},{'extra':1},{'id':'../../bad'},{'campaign_id':'absent'}):
            self.assertIn(self.request('POST','/api/events',{**event,'id':'new-event',**bad})[0],(400,404))
        app.import_prospects(self.db,{'prospects':[prospect(offer='Updated offer')]})
        self.assertEqual(self.request('GET',path)[1]['metadata']['draft'],'A real editable draft')
        self.assertEqual(len(self.request('GET','/api/events')[1]['events']),1)
        app.update_prospect(self.db,'test-owner',{'status':'do_not_contact'})
        for kind in ('contacted','follow_up'):
            self.assertEqual(self.request('POST','/api/events',{**event,'id':kind,'kind':kind})[0],400)
        self.assertEqual(self.request('POST',path,{'draft':'Blocked copy but editable text'})[0],200)
        self.assertEqual(self.request('POST',path,{'follow_up_at':'2026-10-28T12:00:00Z'})[0],400)
        self.assertEqual(self.request('GET','/api/followups')[1]['followups'],[])

    def test_utc_analytics_cohorts_empty_history_daily_target(self):
        from unittest.mock import patch
        import outreach
        with patch.object(outreach,'now',return_value='2026-10-26T18:00:00+00:00'):
            empty=self.request('GET','/api/analytics?days=7')[1]
            self.assertEqual(empty['contacted'],0)
            self.assertEqual(empty['daily_target'],30)
            self.assertEqual(len(empty['daily']),7)
            app.import_prospects(self.db,{'prospects':[prospect(id='other',name='Other')]})
            events=[('a','test-owner','contacted','2026-10-26T12:00:00Z'),('b','test-owner','contacted','2026-10-26T13:00:00Z'),('c','test-owner','replied','2026-10-26T14:00:00Z'),('d','other','replied','2026-10-26T15:00:00Z'),('e','test-owner','opportunity','2026-10-26T16:00:00Z')]
            for key,person,kind,at in events:
                self.assertEqual(self.request('POST','/api/events',{'id':key,'prospect_id':person,'kind':kind,'occurred_at':at})[0],200)
            data=self.request('GET','/api/analytics?days=7')[1]
            self.assertEqual((data['contacted'],data['replied'],data['opportunity']),(1,2,1))
            self.assertEqual(data['reply_rate'],100)
            self.assertEqual(data['replies_without_contact'],1)
            self.assertEqual(data['today_contacted'],1)
            self.assertEqual(data['daily'][-1]['contacted'],2)
            self.assertEqual(self.request('POST','/api/settings',{'daily_target':45})[0],200)
            self.assertEqual(self.request('GET','/api/analytics?days=30')[1]['daily_target'],45)
            for bad in (True,0,10001,'30'):
                self.assertEqual(self.request('POST','/api/settings',{'daily_target':bad})[0],400)
            self.assertEqual(self.request('GET','/api/analytics?days=9')[0],400)

    def test_concurrent_idempotency_database_immutability_and_foreign_keys(self):
        import sqlite3
        import outreach
        from concurrent.futures import ThreadPoolExecutor
        payload={'id':'same-intent','prospect_id':'test-owner','kind':'replied','occurred_at':'2026-10-26T12:00:00Z'}
        with ThreadPoolExecutor(max_workers=6) as pool:
            codes=list(pool.map(lambda _:self.request('POST','/api/events',payload)[0],range(12)))
        self.assertEqual(codes,[200]*12)
        self.assertEqual(len(self.request('GET','/api/events')[1]['events']),1)
        with outreach.connect(self.db) as con:
            for sql in ("UPDATE outreach_events SET kind='contacted'",'DELETE FROM outreach_events'):
                with self.assertRaises(sqlite3.IntegrityError): con.execute(sql)
            with self.assertRaises(sqlite3.IntegrityError): con.execute("INSERT INTO campaign_members VALUES('missing','test-owner')")
        self.assertEqual(self.request('POST','/api/events',{**payload,'id':'not-member','campaign_id':'missing'})[0],404)

class HttpIntegrationTests(DatabaseCase):
    def test_real_http_full_workflow_readback_reimport_and_security(self):
        import threading
        import urllib.request
        import urllib.error
        from datetime import datetime, timezone, timedelta
        app.import_prospects(self.db,{'prospects':[prospect()]})
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        server.db=self.db
        server.allowed_origins=('http://100.72.26.84:3016',)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        def request(path,payload=None,origin=None,host=None):
            headers={'Origin':origin or base,'Content-Type':'application/json'}
            if host: headers['Host']=host
            req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
            try:
                with urllib.request.urlopen(req) as response:
                    self.assertIn("default-src 'self'",response.headers['Content-Security-Policy'])
                    return response.status,json.load(response)
            except urllib.error.HTTPError as e: return e.code,json.load(e)
        self.assertEqual(request('/api/campaigns',{'id':'integration','name':'Integration cohort'})[0],200)
        request('/api/campaigns/integration/members',{'prospect_id':'test-owner','assigned':True})
        self.assertEqual(request('/api/campaigns')[1]['campaigns'][0]['members'],['test-owner'])
        at=datetime.now(timezone.utc)
        metadata={'draft':'Manually written integration draft','follow_up_at':(at-timedelta(hours=1)).isoformat()}
        request('/api/prospects/test-owner/outreach',metadata)
        self.assertEqual(request('/api/prospects/test-owner/outreach')[1]['metadata'],metadata)
        for kind in ('contacted','replied','opportunity','follow_up'):
            payload={'id':'int-'+kind,'prospect_id':'test-owner','campaign_id':'integration','kind':kind,'occurred_at':at.isoformat(),'note':'Temporary integration only'}
            self.assertEqual(request('/api/events',payload)[0],200)
            self.assertEqual(request('/api/events',payload)[0],200)
        self.assertEqual(len(request('/api/events')[1]['events']),4)
        a=request('/api/analytics?days=7')[1]
        self.assertEqual((a['contacted'],a['replied'],a['opportunity'],a['followups_due']),(1,1,1,1))
        app.import_prospects(self.db,{'prospects':[prospect(offer='Refreshed research')]})
        self.assertEqual(request('/api/prospects/test-owner/outreach')[1]['metadata'],metadata)
        self.assertEqual(len(request('/api/events')[1]['events']),4)
        self.assertEqual(request('/api/campaigns')[1]['campaigns'][0]['members'],['test-owner'])
        self.assertEqual(request('/api/settings',{'daily_target':31},host='100.72.26.84:3016',origin='http://100.72.26.84:3016')[0],200)
        self.assertEqual(request('/api/settings')[1]['daily_target'],31)
        self.assertEqual(request('/api/settings',{'daily_target':32},origin='http://evil.test')[0],403)
        self.assertEqual(request('/api/settings',{'daily_target':32},host='evil.test')[0],403)
        for path in ('/api/events','/api/campaigns','/api/prospects/test-owner/outreach','/api/settings'):
            for value in ([],None,True,{'extra':'bad'}):
                if value is not None: self.assertEqual(request(path,value)[0],400)
        request('/api/prospects/test-owner',{'status':'do_not_contact','notes':'No contact'})
        self.assertEqual(request('/api/followups')[1]['followups'],[])
        self.assertEqual(request('/api/events',{'id':'blocked','prospect_id':'test-owner','kind':'contacted','occurred_at':at.isoformat()})[0],400)
        self.assertEqual(len(request('/api/events')[1]['events']),4)
        request('/api/campaigns/integration/members',{'prospect_id':'test-owner','assigned':False})
        self.assertEqual(request('/api/campaigns')[1]['campaigns'][0]['members'],[])
        print('HTTP integration PASS: campaign/member/draft/contact/reply/opportunity/followup/analytics/readback/reimport/suppression/origin security; temporary DB only')

if __name__=='__main__': unittest.main()
