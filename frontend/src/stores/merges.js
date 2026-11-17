import {mergesApi} from '../api/merges.js';
export const mergesStore={items:[],async refresh(){this.items=await mergesApi.list();return this.items;}};
