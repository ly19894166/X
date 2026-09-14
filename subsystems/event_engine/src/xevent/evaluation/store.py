"""Separate label database reusing the existing Ledger transaction/publication fence."""
from pathlib import Path
from ..ledger.store import Ledger, MODELS, digest, ref
from .contracts import SCHEMAS, EvaluationEnvelope


class LabelLedger(Ledger):
    def __init__(self,path,*,feature_path,**kwargs):
        if Path(path).resolve()==Path(feature_path).resolve(): raise ValueError('LABEL_FEATURE_DATABASE_ISOLATION')
        MODELS.update(SCHEMAS)
        super().__init__(path,**kwargs)

    def _put(self,conn,batch,kind,object_id,version,payload,inputs=()):
        if kind not in SCHEMAS: raise ValueError('LABEL_NAMESPACE_ONLY')
        return super()._put(conn,batch,kind,object_id,version,payload,inputs)


class Publisher:
    def __init__(self,ledger): self.ledger=ledger

    def publish(self,cls,identity,payload,*,inputs=(),version=1):
        if cls.__name__ not in SCHEMAS: raise ValueError('LABEL_NAMESPACE_ONLY')
        payload=dict(payload)
        payload.setdefault('as_of',self.ledger.now().isoformat())
        payload.setdefault('policy_version','X_EVALUATION_V0.1')
        payload.setdefault('provenance','离线结算工程；不代表真实Forward或实盘收益')
        def build(conn,view,batch):
            old=max((o for o in view.values() if o.object_id==identity),key=lambda o:o.version,default=None)
            if old and type(old)!=cls: raise ValueError('LABEL_ID_TYPE')
            if version!=(old.version+1 if old else 1): raise ValueError('LABEL_APPEND_ONLY')
            if old and not payload.get('revision_reason'): raise ValueError('REVISION_REASON_REQUIRED')
            deps=list(inputs)+([ref(old)] if old else [])
            self.ledger._put(conn,batch,cls.__name__,identity,version,payload,deps)
        self.ledger._write('P10:'+identity+':'+str(version),digest([payload,list(inputs)]),build)
        return self.ledger.get(identity,version)
