"""Three-way merge of offline relation-draft branches (pure functions, no I/O).

共同版本 base 与左/右两侧离线草案比较：无冲突改动自动保留；同义改写（闭包等价）
不算冲突；一侧撤销的依赖若被合并结果重新推出则阻止并给出推导依据；属性移除与
另一侧新增依赖的引用冲突同样阻止。所有判定只依赖属性闭包，10属性/64依赖内有界。
"""
import hashlib,json
from src.services.normalization import closure

MAX_ATTRIBUTES=10
MAX_DEPENDENCIES=64

def _pairs(dependencies):
    """依赖归一化为单属性RHS对：{(frozenset(lhs), rhs): note}。"""
    out={}
    for dep in dependencies:
        note=dep.get('note') or ''
        for rhs in dep['rhs']:
            key=(frozenset(dep['lhs']),rhs)
            if key not in out or (note and not out[key]):out[key]=note
    return out

def _implies(pairs,lhs,rhs):
    return rhs in closure(set(lhs),[(set(l),r) for l,r in pairs])

def _derivation(pairs,lhs,rhs):
    """从lhs推出rhs的见证链（前置依赖在前），推不出返回None。"""
    derived={a:None for a in lhs}
    ordered=sorted(pairs,key=lambda p:(sorted(p[0]),p[1]))
    changed=True
    while changed:
        changed=False
        for pair in ordered:
            l,r=pair
            if r not in derived and set(l)<=set(derived):derived[r]=pair;changed=True
    if rhs not in derived:return None
    chain=[];seen=set()
    def visit(attr):
        pair=derived[attr]
        if pair is None or pair in seen:return
        seen.add(pair)
        for a in pair[0]:visit(a)
        chain.append(pair)
    visit(rhs)
    return chain

def _fmt(pair):return {'lhs':sorted(pair[0]),'rhs':[pair[1]]}

def _group(pairs,notes):
    """单RHS对按决定项分组回多RHS依赖，确定性排序。"""
    groups={}
    for l,r in sorted(pairs,key=lambda p:(sorted(p[0]),p[1])):
        group=groups.setdefault(l,{'lhs':sorted(l),'rhs':[],'note':''})
        group['rhs'].append(r)
        note=notes.get((l,r),'')
        if note and not group['note']:group['note']=note
    return [{'lhs':g['lhs'],'rhs':sorted(g['rhs']),'note':g['note']} for g in groups.values()]

def fingerprint(attributes,dependencies):
    """目标草案当前状态指纹：预检时记录，确认时比对以拒绝并发修改后的旧确认。"""
    pairs=_pairs(dependencies)
    ordered=sorted(pairs,key=lambda p:(sorted(p[0]),p[1]))
    payload={'attributes':sorted(set(attributes)),'dependencies':[{'lhs':sorted(l),'rhs':r,'note':pairs[(l,r)]} for l,r in ordered]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def merge_snapshots(base,left,right):
    """三路合并。返回 {'merged':{attributes,dependencies},'changes':[...],'conflicts':[...]}。"""
    A0,AL,AR=set(base['attributes']),set(left['attributes']),set(right['attributes'])
    F0,FL,FR=_pairs(base['dependencies']),_pairs(left['dependencies']),_pairs(right['dependencies'])
    changes=[];conflicts=[]
    # 属性三路合并：一侧移除即移除，任一侧新增即加入
    merged_attrs=(AL&AR)|(AL-A0)|(AR-A0)
    for a in sorted(AL-A0):changes.append({'kind':'attribute-added','side':'left','attribute':a})
    for a in sorted(AR-A0):changes.append({'kind':'attribute-added','side':'right','attribute':a})
    for a in sorted(A0-AL):changes.append({'kind':'attribute-removed','side':'left','attribute':a})
    for a in sorted(A0-AR):changes.append({'kind':'attribute-removed','side':'right','attribute':a})
    # 依赖三路合并：归一化对集合上做文本三路合并
    remL,remR=set(F0)-set(FL),set(F0)-set(FR)
    addL,addR=set(FL)-set(F0),set(FR)-set(F0)
    merged_pairs=(set(F0)-remL-remR)|addL|addR
    def source(pair):
        if pair in addL and pair in addR:return 'both'
        if pair in addL:return 'left'
        if pair in addR:return 'right'
        return 'base'
    def sort_key(p):return (sorted(p[0]),p[1])
    for p in sorted(remL|remR,key=sort_key):
        side='both' if p in remL and p in remR else ('left' if p in remL else 'right')
        rephrased=all(_implies(own,p[0],p[1]) for own in ([FL,FR] if side=='both' else ([FL] if side=='left' else [FR])))
        changes.append({'kind':'dependency-rephrased' if rephrased else 'dependency-removed','side':side,'dependency':_fmt(p)})
    for p in sorted(addL|addR,key=sort_key):
        side='both' if p in addL and p in addR else ('left' if p in addL else 'right')
        changes.append({'kind':'dependency-added','side':side,'dependency':_fmt(p)})
    # 冲突一：一侧撤销的规则被合并结果通过传递重新推出（间接恢复已撤销规则）
    for p in sorted(F0,key=sort_key):
        revoked=[side for side,own in (('left',FL),('right',FR)) if not _implies(own,p[0],p[1])]
        if not revoked or not _implies(merged_pairs,p[0],p[1]):continue
        chain=_derivation(merged_pairs,p[0],p[1]) or []
        conflicts.append({'type':'dependency-resurrected','dependency':_fmt(p),'revoked_by':revoked,
            'derivation':[{'lhs':sorted(l),'rhs':[r],'source':source((l,r))} for l,r in chain]})
    # 冲突二：属性被一侧移除，另一侧新增依赖仍引用该属性
    for x in sorted((A0-AL)|(A0-AR)):
        refs=[p for p in merged_pairs if x in p[0] or p[1]==x]
        if refs:conflicts.append({'type':'attribute-dependency','attribute':x,'removed_by':'left' if x in A0-AL else 'right',
            'dependencies':[{'lhs':sorted(l),'rhs':[r],'source':source((l,r))} for l,r in sorted(refs,key=sort_key)]})
    # 冲突三：合并结果超出算法上限或没有属性
    if not merged_attrs:conflicts.append({'type':'empty-attributes','detail':'合并结果至少保留一个属性'})
    if len(merged_attrs)>MAX_ATTRIBUTES:conflicts.append({'type':'limit','detail':'合并结果属性超过10个，请拆分关系'})
    notes={}
    for p in merged_pairs:
        n0,nL,nR=F0.get(p),FL.get(p),FR.get(p)
        if nL==nR:notes[p]=nL or ''
        elif nL==n0:notes[p]=nR or ''
        elif nR==n0:notes[p]=nL or ''
        else:notes[p]=nL or ''
    merged_deps=_group(merged_pairs,notes)
    if len(merged_deps)>MAX_DEPENDENCIES:conflicts.append({'type':'limit','detail':'合并结果依赖超过64条，请合并后重试'})
    return {'merged':{'attributes':sorted(merged_attrs),'dependencies':merged_deps},'changes':changes,'conflicts':conflicts}
