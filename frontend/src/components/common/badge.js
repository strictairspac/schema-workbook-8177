import {RUN_STATES,MERGE_STATES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
const LABELS={...RUN_STATES,...MERGE_STATES};
export const badge=value=>`<span class="badge ${esc(value)}">${esc(LABELS[value]||value)}</span>`;
