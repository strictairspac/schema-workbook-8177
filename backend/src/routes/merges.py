from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import current,writer
from src.schemas.merge import MergeInput,MergeResolveInput
from src.services import merges as service
router=APIRouter()
@router.get('/merges')
def listing(db=Depends(db_session),user=Depends(current)):return service.listing(db)
@router.post('/merges',status_code=201)
def create(data:MergeInput,db=Depends(db_session),user=Depends(writer)):return service.create(db,data,user)
@router.get('/merges/{ident}')
def detail(ident:int,db=Depends(db_session),user=Depends(current)):return service.detail(db,ident)
@router.put('/merges/{ident}')
def resolve(ident:int,data:MergeResolveInput,db=Depends(db_session),user=Depends(writer)):return service.resolve(db,ident,data,user)
@router.post('/merges/{ident}/precheck')
def precheck(ident:int,db=Depends(db_session),user=Depends(writer)):return service.precheck(db,ident,user)
@router.post('/merges/{ident}/confirm')
def confirm(ident:int,db=Depends(db_session),user=Depends(writer)):return service.confirm(db,ident,user)
