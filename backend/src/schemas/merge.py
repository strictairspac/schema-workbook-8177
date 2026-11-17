from pydantic import BaseModel,Field,field_validator,model_validator
def _unique_nonempty(value,message='属性必须唯一且非空，每项不超过40字'):
    if len(set(value))!=len(value) or any(not x.strip() or len(x)>40 for x in value):raise ValueError(message)
    return value
class SnapshotDependency(BaseModel):
    lhs:list[str]=Field(max_length=10)
    rhs:list[str]=Field(min_length=1,max_length=10)
    note:str=Field(default='',max_length=300)
    @field_validator('lhs','rhs')
    @classmethod
    def valid_attributes(cls,v):return _unique_nonempty(v,'依赖属性不能为空或重复')
class Snapshot(BaseModel):
    attributes:list[str]=Field(min_length=1,max_length=10)
    dependencies:list[SnapshotDependency]=Field(default=[],max_length=64)
    @field_validator('attributes')
    @classmethod
    def attributes_valid(cls,v):return _unique_nonempty(v)
    @model_validator(mode='after')
    def refs_valid(self):
        attrs=set(self.attributes)
        if any(not set(d.lhs+d.rhs)<=attrs for d in self.dependencies):raise ValueError('快照依赖引用了快照外属性')
        return self
class MergeInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    relation_id:int=Field(gt=0)
    base:Snapshot
    left:Snapshot
    right:Snapshot
class MergeResolveInput(BaseModel):
    base:Snapshot|None=None
    left:Snapshot|None=None
    right:Snapshot|None=None
