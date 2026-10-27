"""Additive manual outreach workspace. No external accounts or sending."""
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs

SLUG = r'[a-z0-9][a-z0-9_-]{0,99}'

def connect(db):
    con = sqlite3.connect(db, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def now():
    return datetime.now(timezone.utc).isoformat()

def slug(value):
    if not isinstance(value,str) or not re.fullmatch(SLUG,value):
        raise ValueError('Invalid id')
    return value

def fields(payload, allowed, required=()):
    if not isinstance(payload,dict) or set(payload)-set(allowed) or not set(required)<=set(payload):
        raise ValueError('Invalid fields')

def bounded(value, limit, empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):
        raise ValueError('Invalid text')
    return value

def migrate(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workspace_settings(id INTEGER PRIMARY KEY CHECK(id=1),daily_target INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS campaign_members(campaign_id TEXT NOT NULL REFERENCES campaigns(id),prospect_id TEXT NOT NULL REFERENCES prospects(id),PRIMARY KEY(campaign_id,prospect_id));
    CREATE TABLE IF NOT EXISTS outreach_metadata(prospect_id TEXT PRIMARY KEY REFERENCES prospects(id),draft TEXT NOT NULL DEFAULT '',follow_up_at TEXT);
    CREATE TABLE IF NOT EXISTS outreach_events(id TEXT PRIMARY KEY,prospect_id TEXT NOT NULL REFERENCES prospects(id),campaign_id TEXT REFERENCES campaigns(id),kind TEXT NOT NULL,occurred_at TEXT NOT NULL,created_at TEXT NOT NULL,note TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS events_by_date ON outreach_events(occurred_at);
    CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON outreach_events BEGIN SELECT RAISE(ABORT,'Immutable event'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON outreach_events BEGIN SELECT RAISE(ABORT,'Immutable event'); END;
    ''')

def require(con, table, key):
    # table is an internal literal, never an HTTP value.
    row=con.execute('SELECT * FROM '+table+' WHERE id=?',(slug(key),)).fetchone()
    if row is None: raise KeyError(key)
    return dict(row)

def campaigns(con):
    return [{**dict(row),'members':[r[0] for r in con.execute('SELECT prospect_id FROM campaign_members WHERE campaign_id=? ORDER BY prospect_id',(row['id'],))]} for row in con.execute('SELECT * FROM campaigns ORDER BY created_at,id')]

def route(db, method, path, payload=None):
    with connect(db) as con:
        if method=='POST': con.execute('BEGIN IMMEDIATE')
        result = activity_route(con,method,path,payload)
        if result is not None: return result
        if path=='/api/campaigns':
            if method=='GET': return {'campaigns':campaigns(con)}
            fields(payload,('id','name'),('id','name'))
            key=slug(payload['id']); name=bounded(payload['name'],120)
            old=con.execute('SELECT * FROM campaigns WHERE id=?',(key,)).fetchone()
            if old and old['name']!=name: raise ValueError('ID already used')
            con.execute('INSERT OR IGNORE INTO campaigns VALUES(?,?,?)',(key,name,now()))
            return {'campaign':next(c for c in campaigns(con) if c['id']==key)}
        match=re.fullmatch('/api/campaigns/('+SLUG+')/members',path)
        if match and method=='POST':
            fields(payload,('prospect_id','assigned'),('prospect_id','assigned'))
            require(con,'campaigns',match[1]); require(con,'prospects',payload['prospect_id'])
            if type(payload['assigned']) is not bool: raise ValueError('assigned must be boolean')
            if payload['assigned']:
                con.execute('INSERT OR IGNORE INTO campaign_members VALUES(?,?)',(match[1],payload['prospect_id']))
            else:
                con.execute('DELETE FROM campaign_members WHERE campaign_id=? AND prospect_id=?',(match[1],payload['prospect_id']))
            return {'campaign':next(c for c in campaigns(con) if c['id']==match[1])}
    return None

KINDS=('contacted','follow_up','replied','opportunity','won','lost')

def date(value):
    bounded(value,64)
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if 'T' not in value or parsed.tzinfo is None: raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError,OverflowError): raise ValueError('Timezone-aware ISO date required') from None

def metadata(con,key):
    row=con.execute('SELECT draft,follow_up_at FROM outreach_metadata WHERE prospect_id=?',(key,)).fetchone()
    return dict(row) if row else {'draft':'','follow_up_at':None}

def followups(con,at=None):
    at=at or now()
    return [{'prospect_id':r['prospect_id'],'follow_up_at':r['follow_up_at']} for r in con.execute("SELECT m.* FROM outreach_metadata m JOIN prospects p ON p.id=m.prospect_id WHERE m.follow_up_at IS NOT NULL AND m.follow_up_at<=? AND json_extract(p.data,'$.status')!='do_not_contact' ORDER BY m.follow_up_at,m.prospect_id",(at,))]

def activity_route(con,method,path,payload):
    if path=='/api/settings':
        if method=='POST':
            fields(payload,('daily_target',),('daily_target',))
            target=payload['daily_target']
            if type(target) is not int or not 1<=target<=10000: raise ValueError('Target must be 1–10000')
            con.execute('INSERT INTO workspace_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET daily_target=excluded.daily_target',(target,))
        row=con.execute('SELECT daily_target FROM workspace_settings WHERE id=1').fetchone()
        return {'daily_target':row[0] if row else 30}
    if urlsplit(path).path=='/api/analytics' and method=='GET':
        params=parse_qs(urlsplit(path).query,keep_blank_values=True)
        if set(params)-{'days'} or params.get('days',['7']) not in (['7'],['30']): raise ValueError('days must be 7 or 30')
        return analytics(con,int(params.get('days',['7'])[0]))
    match=re.fullmatch('/api/prospects/('+SLUG+')/outreach',path)
    if match:
        p=json.loads(require(con,'prospects',match[1])['data'])
        data=metadata(con,match[1])
        if method=='POST':
            fields(payload,('draft','follow_up_at'))
            if not payload: raise ValueError('Empty metadata')
            if 'draft' in payload: data['draft']=bounded(payload['draft'],20000,True)
            if 'follow_up_at' in payload:
                if payload['follow_up_at'] is not None and p['status']=='do_not_contact': raise ValueError('Suppressed')
                data['follow_up_at']=date(payload['follow_up_at']) if payload['follow_up_at'] is not None else None
            con.execute('INSERT INTO outreach_metadata VALUES(?,?,?) ON CONFLICT(prospect_id) DO UPDATE SET draft=excluded.draft,follow_up_at=excluded.follow_up_at',(match[1],data['draft'],data['follow_up_at']))
        return {'metadata':data}
    if path=='/api/followups' and method=='GET': return {'followups':followups(con)}
    if path=='/api/events':
        if method=='GET': return {'events':[dict(r) for r in con.execute('SELECT * FROM outreach_events ORDER BY occurred_at DESC,id')]}
        fields(payload,('id','prospect_id','campaign_id','kind','occurred_at','note'),('id','prospect_id','kind','occurred_at'))
        data={'id':slug(payload['id']),'prospect_id':slug(payload['prospect_id']),'campaign_id':payload.get('campaign_id'),'kind':payload['kind'],'occurred_at':date(payload['occurred_at']),'note':bounded(payload.get('note',''),2000,True)}
        if data['kind'] not in KINDS: raise ValueError('Unsupported event kind')
        if data['campaign_id'] is not None: slug(data['campaign_id'])
        old=con.execute('SELECT * FROM outreach_events WHERE id=?',(data['id'],)).fetchone()
        if old:
            if any(old[k]!=v for k,v in data.items()): raise ValueError('Event id reused')
            return {'event':dict(old)}
        p=json.loads(require(con,'prospects',data['prospect_id'])['data'])
        if data['kind'] in ('contacted','follow_up') and p['status']=='do_not_contact': raise ValueError('Suppressed')
        if data['campaign_id'] is not None:
            require(con,'campaigns',data['campaign_id'])
            if not con.execute('SELECT 1 FROM campaign_members WHERE campaign_id=? AND prospect_id=?',(data['campaign_id'],data['prospect_id'])).fetchone(): raise ValueError('Not a campaign member')
        data['created_at']=now()
        con.execute('INSERT INTO outreach_events(id,prospect_id,campaign_id,kind,occurred_at,note,created_at) VALUES(:id,:prospect_id,:campaign_id,:kind,:occurred_at,:note,:created_at)',data)
        return {'event':data}
    return None

def analytics(con,days):
    end=datetime.fromisoformat(now()).astimezone(timezone.utc)
    start=end.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=days-1)
    daily=[{'date':(start+timedelta(days=i)).date().isoformat(),**{k:0 for k in KINDS[:4]}} for i in range(days)]
    people={k:set() for k in KINDS}
    today=set()
    for row in con.execute('SELECT * FROM outreach_events WHERE occurred_at>=? AND occurred_at<=?',(start.isoformat(),end.isoformat())):
        at=datetime.fromisoformat(row['occurred_at'])
        people[row['kind']].add(row['prospect_id'])
        if row['kind'] in daily[0]: daily[(at.date()-start.date()).days][row['kind']]+=1
        if row['kind']=='contacted' and at.date()==end.date(): today.add(row['prospect_id'])
    contacted=people['contacted']
    row=con.execute('SELECT daily_target FROM workspace_settings WHERE id=1').fetchone()
    return {'days':days,'timezone':'UTC','start':start.isoformat(),'end':end.isoformat(),'daily':daily,
        'contacted':len(contacted),'replied':len(people['replied']),'opportunity':len(people['opportunity']),
        'followups_due':len(followups(con,end.isoformat())),
        'reply_rate':round(100*len(contacted & people['replied'])/len(contacted),1) if contacted else None,
        'opportunity_rate':round(100*len(contacted & people['opportunity'])/len(contacted),1) if contacted else None,
        'replies_without_contact':len(people['replied']-contacted),'opportunities_without_contact':len(people['opportunity']-contacted),
        'today_contacted':len(today),'daily_target':row[0] if row else 30}
