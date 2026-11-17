import {api} from './client.js';
export const mergesApi={list:()=>api('/merges'),detail:id=>api('/merges/'+id),create:data=>api('/merges','POST',data),resolve:(id,data)=>api('/merges/'+id,'PUT',data),precheck:id=>api('/merges/'+id+'/precheck','POST'),confirm:id=>api('/merges/'+id+'/confirm','POST')};
