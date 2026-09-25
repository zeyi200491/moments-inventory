const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../src/moments_inventory/showcase_web/static');
function helpers() {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(root, 'shared/product-utils.js'), 'utf8'), context);
  return context.ShowcaseUtils;
}
test('稳定标识优先且保留旧标识', () => {
  const u = helpers();
  assert.equal(u.productKey({publicId:'p_123', productId:'旧/编号'}), 'p_123');
  assert.equal(u.productKey({productId:'旧/编号'}), '旧/编号');
});
test('远程图片不加斜线且拒绝危险协议', () => {
  const u = helpers();
  assert.equal(u.imageUrl('https://example.com/a.jpg'), 'https://example.com/a.jpg');
  assert.equal(u.imageUrl('media/a.jpg'), '/media/a.jpg');
  assert.equal(u.imageUrl('javascript:alert(1)'), '');
});
test('草稿仅包含变更字段', () => {
  const u = helpers();
  assert.equal(JSON.stringify(u.changedFields({model:'A',displayPrice:12,recommendTags:['a']},{model:'B',displayPrice:12,recommendTags:['a']})), '{"model":"B"}');
});
test('商品管理包含明确的批量作用范围和价格段控件', () => {
  const html = fs.readFileSync(path.join(root, 'admin.html'), 'utf8');
  assert.match(html, /id="bulkScopeInput"/);
  assert.match(html, /value="selected"/);
  assert.match(html, /value="filtered"/);
  assert.match(html, /value="all"/);
  assert.match(html, /id="bulkPriceRangeInput"/);
  for (const value of ['up_to_200', '201_300', '301_600', '601_800', '801_plus', 'custom']) {
    assert.match(html, new RegExp(`value="${value}"`));
  }
  assert.ok(html.indexOf('id="bulkPricingPanel"') > html.indexOf('<h2>商品管理</h2>'));
  assert.match(html, /id="bulkPreviewStatus"[^>]*aria-live="polite"/);
});

function pageContext(file) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, { value: '', hidden: false, dataset: {}, listeners: {}, addEventListener(event, callback) {this.listeners[event] = callback;}, removeAttribute() {}, setAttribute() {} });
    return nodes.get(id);
  }
  const context = vm.createContext({
    console, URL, URLSearchParams, AbortController, setTimeout, clearTimeout, alert() {}, crypto: { randomUUID: () => 'test-key' },
    document: { getElementById: node, querySelector: () => null, querySelectorAll: () => [], addEventListener() {} },
    window: { addEventListener() {}, history: {replaceState() {}}, location: {search:'',pathname:'/'}, setTimeout() {}, scrollTo() {} },
    sessionStorage: {getItem: () => null, removeItem() {}},
    fetch: async () => { throw new Error('未配置请求'); },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'shared/product-utils.js'), 'utf8'), context);
  const source = fs.readFileSync(path.join(root, file), 'utf8').replace('initListPage().catch(showStartupError);', '').replace('initDetailPage().catch(showStartupError);', '');
  vm.runInContext(source, context);
  context.nodes = nodes;
  return context;
}
test('后台追加固定80条并防止旧请求覆盖', async () => {
  const c = pageContext('admin.js');
  vm.runInContext('renderAdminProducts = () => {};', c);
  const pending = [];
  c.fetch = (url) => new Promise((resolve) => pending.push({url, resolve}));
  const first = vm.runInContext('loadProducts()', c);
  const second = vm.runInContext('loadProducts()', c);
  pending[1].resolve({ok:true,json:async () => ({products:[{publicId:'new'}],total:100,hasMore:true})});
  await second;
  pending[0].resolve({ok:true,json:async () => ({products:[{publicId:'old'}],total:1,hasMore:false})});
  await first;
  assert.equal(vm.runInContext('adminState.products[0].publicId', c), 'new');
  const appended = vm.runInContext('loadProducts({append:true})', c);
  assert.match(pending[2].url, /limit=80&offset=1/);
  pending[2].resolve({ok:true,json:async () => ({products:[{publicId:'next'}],total:100,hasMore:true})});
  await appended;
  assert.equal(vm.runInContext('adminState.products.length', c), 2);
});
test('客户恢复无进展立即停止且失败显示重试', async () => {
  const c = pageContext('showcase.js');
  vm.runInContext('renderList = () => {}; renderBrands = () => {}; renderQuickFilters = () => {};', c);
  c.sessionStorage.getItem = () => JSON.stringify({loadedCount:999});
  let calls = 0;
  c.fetch = async () => { calls++; return {ok:true,json:async () => ({products:[],hasMore:true,total:999})}; };
  await vm.runInContext('restoreListStateIfAvailable()', c);
  assert.equal(calls, 1);
  c.fetch = async () => ({ok:false,status:503});
  assert.equal(await vm.runInContext('loadProductPage({reset:true})', c), false);
  assert.match(vm.runInContext('state.loadError', c), /加载失败/);
});
test('客户自动恢复最多请求五页', async () => {
  const c = pageContext('showcase.js');
  vm.runInContext('renderList = () => {}; renderBrands = () => {}; renderQuickFilters = () => {};', c);
  c.sessionStorage.getItem = () => JSON.stringify({loadedCount:99999});
  let calls = 0;
  c.fetch = async () => ({ok:true,json:async () => ({products:[{publicId:String(++calls)}],hasMore:true,total:99999})});
  await vm.runInContext('restoreListStateIfAvailable()', c);
  assert.equal(calls, 5);
});
test('操作记录安全显示筛选条件并按操作状态提供撤销', async () => {
  const c = pageContext('admin.js');
  c.fetch = async (url) => {
    assert.equal(url, '/api/admin/operations');
    return {ok:true,json:async () => ({operations:[
      {operationId:'price',operationType:'price',summary:'改价',filterText:'scope=<all>&sold=false',createdAt:'1',undoneAt:''},
      {operationId:'hide',operationType:'hide',summary:'隐藏',filterText:'scope=all',createdAt:'2',undoneAt:''},
      {operationId:'show',operationType:'show',summary:'显示',filterText:'scope=all',createdAt:'3',undoneAt:''},
      {operationId:'undo',operationType:'undo',summary:'撤销',filterText:'scope=all',createdAt:'4',undoneAt:''},
      {operationId:'undone',operationType:'price',summary:'已撤销改价',filterText:'scope=all',createdAt:'5',undoneAt:'6'},
    ]})};
  };

  await vm.runInContext('loadOperations()', c);
  const html = c.nodes.get('operationList').innerHTML;
  const operationRow = (id) => {
    const match = html.match(new RegExp(`<div[^>]*data-operation-id="${id}"[\\s\\S]*?</div>`));
    assert.ok(match, `缺少操作记录 ${id}`);
    return match[0];
  };

  assert.match(operationRow('price'), /scope=&lt;all&gt;&amp;sold=false/);
  assert.doesNotMatch(operationRow('price'), /scope=<all>&sold=false/);
  assert.match(operationRow('price'), /class="undo-operation"/);
  assert.match(operationRow('hide'), /class="undo-operation"/);
  assert.match(operationRow('show'), /class="undo-operation"/);
  assert.doesNotMatch(operationRow('undo'), /class="undo-operation"/);
  assert.doesNotMatch(operationRow('undone'), /class="undo-operation"/);
});
test('批量执行拒绝双击且网络失败后重用幂等键', async () => {
  const c = pageContext('admin.js');
  vm.runInContext('adminState.lastBulkRequest = {previewId:"preview-1",idempotencyKey:"key-1"}; loadProducts = loadSections = loadDiagnostics = loadOperations = async () => {};', c);
  const pending = [];
  c.fetch = (url, options) => new Promise((resolve, reject) => pending.push({url, options, resolve, reject}));
  const click = c.nodes.get('applyBulkButton').listeners.click;
  const first = click();
  await click();
  assert.equal(pending.length, 1);
  pending[0].reject(new Error('连接断开'));
  await first;
  const retry = click();
  assert.equal(pending[1].options.body, pending[0].options.body);
  assert.deepEqual(JSON.parse(pending[1].options.body), {previewId:'preview-1',idempotencyKey:'key-1'});
  pending[1].resolve({ok:true,json:async () => ({updatedCount:2})});
  await retry;
  assert.equal(vm.runInContext('adminState.lastBulkRequest',c), null);
});
test('保存仅提交草稿变化与原版本并保留其他行草稿', async () => {
  const c = pageContext('admin.js');
  vm.runInContext(`adminState.products = [{publicId:'p1',model:'A',rowVersion:3}];
    adminState.drafts.set('p1', {original:adminState.products[0],changes:{model:'B'}});
    adminState.drafts.set('p2', {original:{rowVersion:1},changes:{brand:'未保存'}});
    loadSections = async () => {};`, c);
  let request;
  c.fetch = async (url, options) => {request = {url, options};return {ok:true,json:async () => ({publicId:'p1',model:'B',rowVersion:4})};};
  const row = {dataset:{productId:'p1'}};
  const target = {disabled:false, classList:{contains:name => name === 'admin-save-product'}, closest:() => row};
  await c.nodes.get('adminProductList').listeners.click({target});
  assert.deepEqual(JSON.parse(request.options.body), {model:'B',expectedVersion:3});
  assert.equal(vm.runInContext('adminState.products[0].rowVersion',c),4);
  assert.equal(vm.runInContext('adminState.drafts.has("p2")',c),true);
});
