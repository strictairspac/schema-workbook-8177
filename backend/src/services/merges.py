from datetime import datetime,timezone
from sqlalchemy import select,update
from fastapi import HTTPException
from src.models.entities import Relation,Dependency,Merge,Audit
from src.constants.enums import MERGE_STATES
from src.utils.serialization import record
from .common import save
from . import merge_engine as engine
def listing(db):return [record(x) for x in db.scalars(select(Merge).order_by(Merge.id.desc()))]
def detail(db,ident):
    obj=db.get(Merge,ident)
    if not obj:raise HTTPException(404,'合并会话不存在')
    return record(obj)
def _fingerprint(db,relation_id):
    relation=db.get(Relation,relation_id)
    if not relation:raise HTTPException(404,'目标关系不存在')
    deps=list(db.scalars(select(Dependency).where(Dependency.relation_id==relation_id)))
    return engine.fingerprint(relation.attributes,[{'lhs':d.lhs,'rhs':d.rhs,'note':d.note} for d in deps])
def _precheck(obj):
    result=engine.merge_snapshots(obj.base_snapshot,obj.left_snapshot,obj.right_snapshot)
    obj.precheck=result;obj.status=MERGE_STATES[1] if result['conflicts'] else MERGE_STATES[0]
def _merged_valid(merged):
    """应用前复核持久化的预检结果，损坏/篡改一律拒绝而不是写入垃圾。"""
    try:
        attrs,deps=merged['attributes'],merged['dependencies']
        if not isinstance(attrs,list) or not 1<=len(attrs)<=10 or len(set(attrs))!=len(attrs):return False
        if any(not isinstance(a,str) or not a.strip() for a in attrs):return False
        if not isinstance(deps,list) or len(deps)>64:return False
        for d in deps:
            if not isinstance(d.get('lhs'),list) or not isinstance(d.get('rhs'),list) or not 1<=len(d['rhs'])<=10:return False
            if any(not isinstance(x,str) or not x.strip() for x in d['lhs']+d['rhs']):return False
            if not set(d['lhs']+d['rhs'])<=set(attrs):return False
        return True
    except Exception:return False
def create(db,data,user):
    if not db.get(Relation,data.relation_id):raise HTTPException(404,'目标关系不存在')
    obj=Merge(name=data.name,relation_id=data.relation_id,base_snapshot=data.base.model_dump(),
        left_snapshot=data.left.model_dump(),right_snapshot=data.right.model_dump(),
        created_by=user.email,target_fingerprint=_fingerprint(db,data.relation_id))
    _precheck(obj)
    return save(db,obj,user,'创建合并会话 '+data.name)
def _revalidate(db,ident,data,user,action):
    obj=db.get(Merge,ident)
    if not obj:raise HTTPException(404,'合并会话不存在')
    if obj.status==MERGE_STATES[2]:raise HTTPException(409,'会话已合并，不能再修改')
    if data is not None:
        for field in ('base','left','right'):
            value=getattr(data,field)
            if value is not None:setattr(obj,field+'_snapshot',value.model_dump())
    obj.target_fingerprint=_fingerprint(db,obj.relation_id);obj.updated_at=datetime.now(timezone.utc)
    _precheck(obj)
    return save(db,obj,user,action+obj.name)
def resolve(db,ident,data,user):return _revalidate(db,ident,data,user,'重新预检合并会话 ')
def precheck(db,ident,user):return _revalidate(db,ident,None,user,'刷新预检合并会话 ')
def confirm(db,ident,user):
    obj=db.scalar(select(Merge).where(Merge.id==ident).with_for_update())
    if not obj:raise HTTPException(404,'合并会话不存在')
    if obj.status==MERGE_STATES[2]:return record(obj)  # 幂等：重复确认不重复应用
    if obj.status==MERGE_STATES[1]:raise HTTPException(409,'存在未解决的冲突，请先解决分支并重新预检')
    relation=db.scalar(select(Relation).where(Relation.id==obj.relation_id).with_for_update())
    if not relation:raise HTTPException(404,'目标关系不存在')
    deps=list(db.scalars(select(Dependency).where(Dependency.relation_id==relation.id)))
    if engine.fingerprint(relation.attributes,[{'lhs':d.lhs,'rhs':d.rhs,'note':d.note} for d in deps])!=obj.target_fingerprint:
        raise HTTPException(409,'预检后目标草案已被并发修改，请重新预检')
    merged=(obj.precheck or {}).get('merged')
    if not merged or not _merged_valid(merged):raise HTTPException(409,'预检结果缺失或已失效，请重新预检')
    now=datetime.now(timezone.utc)
    claimed=db.execute(update(Merge).where(Merge.id==ident,Merge.status==MERGE_STATES[0]).values(status=MERGE_STATES[2],merged_at=now)).rowcount
    if claimed!=1:  # 并发确认已被另一侧抢先应用，本次直接返回合并结果
        db.rollback();return record(db.get(Merge,ident))
    try:
        relation.attributes=list(merged['attributes'])
        for d in deps:db.delete(d)
        for d in merged['dependencies']:db.add(Dependency(relation_id=relation.id,lhs=d['lhs'],rhs=d['rhs'],note=d.get('note','') or ''))
        db.add(Audit(actor=user.email,action='确认合并 '+obj.name+' → '+relation.code))
        db.commit()  # 草案与依赖同一事务整体生效；任何失败回滚保留旧版
    except Exception:
        db.rollback();raise HTTPException(500,'合并应用失败，已保留原版本，请重新预检后重试')
    db.refresh(obj)
    return record(obj)
