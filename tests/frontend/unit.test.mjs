import assert from 'node:assert/strict';
import test from 'node:test';

import { unwrap } from '../../pages/style-manager/src/api.js';
import { validateLayer } from '../../pages/style-manager/src/layer.js';
import {
  acceptSavedLayer,
  allSids,
  counts,
  revisionFor,
  store,
} from '../../pages/style-manager/src/store.js';
import {
  buildFullDataPreview,
  donutSegments,
} from '../../pages/style-manager/src/overview.js';


function resetStore() {
  store.snapshot = {
    universal: { b: [{ content: 'u' }] },
    contextual: { a: [{ scene: 's', behavior: 'b' }] },
    specific: { b: [{ content: 'p', trigger_regex: 'p' }] },
    revisions: {
      universal: { a: 'ua', b: 'ub' },
      contextual: { a: 'ca', b: 'cb' },
      specific: { a: 'sa', b: 'sb' },
    },
  };
  store.sid = 'a';
  store.model = { universal: [], contextual: [], specific: [] };
  store.dirty = {};
  store.caps = { universal: 10, contextual: 150, specific: 200 };
}


test('store derives stable sessions and counts', () => {
  resetStore();
  assert.deepEqual(allSids(), ['a', 'b']);
  assert.deepEqual(counts('b'), { u: 1, c: 0, p: 1 });
  assert.equal(revisionFor('contextual'), 'ca');
});


test('saved layer updates the addressed session only', () => {
  resetStore();
  const applied = acceptSavedLayer('universal', [{ content: 'new' }], 'new-rev', 'b');
  assert.equal(applied, false);
  assert.equal(store.snapshot.universal.b[0].content, 'new');
  assert.equal(store.snapshot.revisions.universal.b, 'new-rev');
  assert.deepEqual(store.model.universal, []);
});


test('api unwrap keeps direct values and unwraps envelopes', () => {
  assert.deepEqual(unwrap({ status: 'ok', data: { value: 1 } }), { value: 1 });
  assert.deepEqual(unwrap({ value: 1 }), { value: 1 });
  assert.equal(unwrap(null), null);
});


test('donut segments retain semantic colors after zero filtering', () => {
  assert.deepEqual(donutSegments({ u: 0, c: 2, p: 3 }), [
    { key: 'contextual', value: 2 },
    { key: 'specific', value: 3 },
  ]);
});


test('full preview labels specific data accurately', () => {
  assert.equal(buildFullDataPreview({
    universal: [{ content: '简短' }],
    contextual: [{ scene: '问候', behavior: '回应' }],
    specific: [{ content: '内部梗' }],
  }), '通用风格：简短；情境提示：问候→回应；特定层数据：内部梗');
});


test('layer validation catches empty and duplicate entries before save-all', () => {
  resetStore();
  store.model.universal = [{ content: 'same' }, { content: 'same' }];
  assert.equal(validateLayer('universal').ok, false);
  store.model.specific = [{ content: 'meme', trigger_regex: '(' }];
  assert.equal(validateLayer('specific').ok, false);
});
