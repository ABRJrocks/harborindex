"""Toy vectors illustrate rank fusion; they are not model embeddings."""

from .report import compare
from .search import Index
from .validation import Document, require

MODEL='toy-workflow-3d-v1'
DOCUMENTS=[
    Document('key-rotation','Rotate service credentials in stages. Create a new token, update consumers, verify traffic and revoke the previous token.','Service credential rotation',{'team':'platform','kind':'runbook'},[1,0,0]),
    Document('secret-expiry','Credential expiry needs advance alerts, a named owner and a tested renewal process.','Expiry and renewal',{'team':'platform','kind':'policy'},[.9,.1,0]),
    Document('job-token','A batch job uses credentials to read a database backup. Review the job account permissions.','Batch job permissions',{'team':'platform','kind':'reference'},[.5,.5,0]),
    Document('backup-restore','Restore a database backup into an isolated environment and verify row counts, constraints and application checks.','Database restore rehearsal',{'team':'data','kind':'runbook'},[0,1,0]),
    Document('recovery-point','A recovery plan must account for new transactions written after the last verified recovery point.','Recovery point review',{'team':'data','kind':'policy'},[.1,.95,0]),
    Document('replication','Check replication lag and reconcile the source and target before a database migration.','Replication checks',{'team':'data','kind':'checklist'},[0,.85,.15]),
    Document('canary-traffic','Switch a small traffic cohort to the canary, compare errors and latency, and review the rollback condition.','Canary traffic change',{'team':'platform','kind':'runbook'},[0,0,1]),
    Document('dns-routing','Routing changes need observed DNS behavior and a plan for cached clients. Traffic may remain on the old destination.','DNS routing review',{'team':'platform','kind':'reference'},[0,.1,.95]),
    Document('handoff','Name the next service owner and share the deployment report, remaining risks and follow-up tasks.','Operational handoff',{'team':'platform','kind':'checklist'},[.3,.3,.4]),
]
QUERIES=[
    {'name':'Credential rotation','query':'rotate service credentials','vector':[1,0,0],'where':{'team':'platform'}},
    {'name':'Database recovery','query':'restore database backup','vector':[0,1,0],'where':{'team':'data'}},
    {'name':'Traffic routing','query':'switch traffic canary','vector':[0,0,1],'where':{'team':'platform'}},
]


def run_demo():
    with Index.create(':memory:',dimensions=3,model=MODEL) as index:
        index.upsert('playbooks',DOCUMENTS,model=MODEL)
        index.upsert('unrelated',[Document('excluded','rotate credentials restore database traffic',vector=[1,0,0])],model=MODEL)
        report=compare(index,'playbooks',QUERIES,model=MODEL,k=5,candidate_limit=10)
        expected=['key-rotation','backup-restore','canary-traffic']
        for case,top in zip(report['cases'],expected):
            hits=case['results']['hybrid']['hits']
            require(hits[0]['id']==top,'Demo top-result check failed')
            require(all(hit['namespace']=='playbooks' and hit['metadata']['team']==case['where']['team'] for hit in hits),
                    'Demo scope check failed')
        report['toy_vectors']=True
        return report
