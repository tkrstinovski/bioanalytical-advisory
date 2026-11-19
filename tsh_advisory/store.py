import hashlib, json, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()
def canonical(value): return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def uid(): return uuid.uuid4().hex

class Store:
    def __init__(self,root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, title TEXT, data TEXT, version INTEGER);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, case_id TEXT, case_version INTEGER, mode TEXT, data TEXT, stopped INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, data TEXT, prev TEXT, hash TEXT);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, run_id TEXT, section TEXT, role TEXT, actor TEXT, action TEXT, packet_hash TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS usage(run_id TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, run_id TEXT, agent TEXT, objective TEXT, status TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY, data TEXT);''')
            c.execute('CREATE TABLE IF NOT EXISTS planning_revisions(run_id TEXT, revision INTEGER, packet_hash TEXT, data TEXT, PRIMARY KEY(run_id,revision))')
            if 'deleted_at' not in [row[1] for row in c.execute('PRAGMA table_info(cases)')]:
                c.execute('ALTER TABLE cases ADD COLUMN deleted_at TEXT')
    def connect(self):
        c=sqlite3.connect(self.root/'organization.sqlite',timeout=30); c.row_factory=sqlite3.Row; return c
    def _event(self,c,run,event,actor,data):
        prev=c.execute('SELECT hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1',(run,)).fetchone()
        prev=prev[0] if prev else ''
        payload=dict(timestamp=now(),run_id=run,event=event,actor=actor,data=data)
        h=digest({'previous':prev,'event':payload})
        c.execute('INSERT INTO events(run_id,data,prev,hash) VALUES(?,?,?,?)',(run,canonical(payload),prev,h))
    def event(self,run,event,actor,data):
        with self.connect() as c: self._event(c,run,event,actor,data)
    def save_case(self,data,case_id=None,expected=None):
        case_id=case_id or uid()
        with self.connect() as c:
            old=c.execute('SELECT version,deleted_at FROM cases WHERE id=?',(case_id,)).fetchone()
            if old and old['deleted_at']:raise ValueError('Project is deleted. Restore it before editing.')
            version=old[0] if old else 0
            if expected is not None and version!=expected: raise ValueError('Draft changed. Reload before saving.')
            c.execute('INSERT OR REPLACE INTO cases(id,title,data,version) VALUES(?,?,?,?)',(case_id,data['title'],canonical(data),version+1))
            self._event(c,'case:'+case_id,'draft_saved','requester',dict(version=version+1,data=data))
        return case_id
    def cases(self):
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT id,title,version FROM cases WHERE deleted_at IS NULL')]
    def case(self,cid):
        with self.connect() as c: r=c.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
        if not r: raise ValueError('Case not found')
        if r['deleted_at']:raise ValueError('Project is deleted. Restore it from Deleted projects to continue.')
        return dict(id=r['id'],version=r['version'],data=json.loads(r['data']))
    def create_run(self,cid,mode):
        case=self.case(cid); rid=uid()
        with self.connect() as c:
            c.execute('INSERT INTO runs(id,case_id,case_version,mode,data) VALUES(?,?,?,?,?)',(rid,cid,case['version'],mode,'{}'))
            self._event(c,rid,'run_started','requester',dict(case=case,mode=mode))
        return rid
    def run(self,rid):
        with self.connect() as c: r=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not r: raise ValueError('Run not found')
        return {**dict(r),'data':json.loads(r['data'])}
    def save_run(self,rid,data):
        with self.connect() as c: c.execute('UPDATE runs SET data=? WHERE id=?',(canonical(data),rid))
    def bind_intake_version(self,rid,expected_version,actor,details):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT cases.version FROM cases JOIN runs ON runs.case_id=cases.id WHERE runs.id=?',(rid,)).fetchone()
            if not current or current[0]!=expected_version:raise ValueError('Intake changed again while recalculating. Apply the latest intake before approval.')
            c.execute('UPDATE runs SET case_version=? WHERE id=?',(expected_version,rid))
            self._event(c,rid,'intake_applied',actor,details)
    def archive_revision(self,rid,state,actor):
        with self.connect() as c:
            n=c.execute('SELECT COALESCE(MAX(revision),0)+1 FROM planning_revisions WHERE run_id=?',(rid,)).fetchone()[0]
            c.execute('INSERT INTO planning_revisions VALUES(?,?,?,?)',(rid,n,digest(state.get('packet',{})),canonical(state)))
            self._event(c,rid,'planning_revision_archived',actor,{'archived_revision':n,'packet_hash':digest(state.get('packet',{}))})
        return n+1
    def revisions(self,rid):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT revision,packet_hash,data FROM planning_revisions WHERE run_id=? ORDER BY revision',(rid,))]
    def runs(self,cid):
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT id,mode,stopped FROM runs WHERE case_id=? ORDER BY rowid DESC',(cid,))]
    def stop(self,rid,actor):
        with self.connect() as c:
            c.execute('UPDATE runs SET stopped=1 WHERE id=?',(rid,))
            self._event(c,rid,'kill_switch',actor,{})
    def ensure_active(self,rid):
        run=self.run(rid)
        self.case(run['case_id'])
        if run['stopped']: raise ValueError('Run stopped. Create a new run after intervention.')
    def delete_case(self,cid,actor='local project owner'):
        with self.connect() as c:
            result=c.execute('UPDATE cases SET deleted_at=? WHERE id=? AND deleted_at IS NULL',(now(),cid))
            if result.rowcount!=1:raise ValueError('Active project not found.')
            self._event(c,'case:'+cid,'project_deleted',actor,{'case_id':cid,'retention':'Moved to Deleted projects; run/evidence records retained.'})
    def deleted_cases(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT id,title,deleted_at FROM cases WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC')]
    def restore_case(self,cid,actor='local project owner'):
        with self.connect() as c:
            result=c.execute('UPDATE cases SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL',(cid,))
            if result.rowcount!=1:raise ValueError('Deleted project not found.')
            self._event(c,'case:'+cid,'project_restored',actor,{'case_id':cid})
    def events(self,rid):
        with self.connect() as c: rows=c.execute('SELECT * FROM events WHERE run_id=? ORDER BY seq',(rid,)).fetchall()
        return [{**dict(r),'data':json.loads(r['data'])} for r in rows]
    def verify(self,rid):
        prev=''
        for r in self.events(rid):
            if r['prev']!=prev or digest({'previous':prev,'event':r['data']})!=r['hash']: return False
            prev=r['hash']
        return True
    def decisions(self,rid):
        with self.connect() as c: rows=c.execute('SELECT data FROM decisions WHERE run_id=? ORDER BY rowid',(rid,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def task(self,rid,agent,objective,status,data):
        tid=digest([rid,agent,objective,data.get('iteration',0)])
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO tasks VALUES(?,?,?,?,?,?)',(tid,rid,agent,objective,status,canonical(data)))
        return tid
    def tasks(self,rid):
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM tasks WHERE run_id=?',(rid,))]
    def usage(self,rid):
        with self.connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT data FROM usage WHERE run_id=?',(rid,))]
    def record_usage(self,rid,data):
        with self.connect() as c: c.execute('INSERT INTO usage VALUES(?,?)',(rid,canonical(data)))
