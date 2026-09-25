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
  assert.match(html, /id="bulkConfirmStatus"[^>]*role="alert"/);
  assert.match(html, /showcase\.css\?v=20260925-bulk-price-workflow/);
  assert.match(html, /admin\.js\?v=20260925-bulk-price-workflow/);
});

function pageContext(file) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', hidden: false, disabled: false, checked: false, open: false,
      textContent: '', innerHTML: '', dataset: {}, listeners: {},
      tagName: id.toLowerCase().includes('input') ? 'INPUT' : 'SELECT',
      classList: { contains() { return false; } },
      addEventListener(event, callback) { this.listeners[event] = callback; },
      removeAttribute() {}, setAttribute() {},
      focus() { context.document.activeElement = this; },
      showModal() { this.open = true; },
      close(returnValue = '') {
        this.open = false;
        this.returnValue = returnValue;
        this.listeners.close?.();
      },
    });
    return nodes.get(id);
  }
  const context = vm.createContext({
    console, URL, URLSearchParams, AbortController, setTimeout, clearTimeout, alert() {}, crypto: { randomUUID: () => 'test-key' },
    document: {
      activeElement: null,
      getElementById: node,
      querySelector: () => null,
      querySelectorAll(selector) {
        if (selector === '.bulk-price-action-field') {
          return [node('bulkPriceModeField'), node('bulkAmountField')];
        }
        return [];
      },
      addEventListener() {},
    },
    window: { addEventListener() {}, history: {replaceState() {}}, location: {search:'',pathname:'/',href:''}, setTimeout() {}, scrollTo() {} },
    sessionStorage: {getItem: () => null, removeItem() {}},
    fetch: async () => { throw new Error('未配置请求'); },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'shared/product-utils.js'), 'utf8'), context);
  const source = fs.readFileSync(path.join(root, file), 'utf8').replace('initListPage().catch(showStartupError);', '').replace('initDetailPage().catch(showStartupError);', '');
  vm.runInContext(source, context);
  context.nodes = nodes;
  return context;
}

test('批量价格段转换为包含边界且默认排除隐藏和已售商品', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkOperationInput').value = 'price';
  c.nodes.get('bulkPriceRangeInput').value = '201_300';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('bulkSoldInput').value = 'false';
  c.nodes.get('bulkPriceModeInput').value = 'increment';
  c.nodes.get('batchAmountInput').value = '50';

  const request = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(request), JSON.stringify({
    scope: 'filtered', operation: 'price', priceMode: 'increment', amount: 50,
    productIds: [], filters: {
      query: '', brands: [], priceMin: 201, priceMax: 300,
      visible: true, sold: false, hasBodyImage: null,
      hasSampleImage: null, manualPrice: null, reviewState: '', tags: [],
    },
  }));

  const ranges = {
    all: [null, null], up_to_200: [null, 200], '201_300': [201, 300],
    '301_600': [301, 600], '601_800': [601, 800], '801_plus': [801, null],
  };
  for (const [value, expected] of Object.entries(ranges)) {
    c.nodes.get('bulkPriceRangeInput').value = value;
    assert.equal(JSON.stringify(vm.runInContext('selectedBulkPriceRange()', c)), JSON.stringify(expected));
  }

  vm.runInContext("adminState.selectedProductIds = new Set(['p1','p2'])", c);
  c.nodes.get('bulkScopeInput').value = 'selected';
  const selectedRequest = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(selectedRequest.productIds), JSON.stringify(['p1', 'p2']));

  c.nodes.get('adminBrandFilterInput').value = '佳能';
  c.nodes.get('adminMinPriceInput').value = '250';
  c.nodes.get('adminMaxPriceInput').value = '700';
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkPriceRangeInput').value = '301_600';
  const intersectedRequest = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(intersectedRequest.filters.brands), JSON.stringify(['佳能']));
  assert.equal(intersectedRequest.filters.priceMin, 301);
  assert.equal(intersectedRequest.filters.priceMax, 600);

  c.nodes.get('adminMinPriceInput').value = '400';
  vm.runInContext('updateBulkScopeSummary()', c);
  assert.match(c.nodes.get('bulkScopeSummary').textContent, /400～600 元/);

  c.nodes.get('adminMinPriceInput').value = '700';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /没有交集/);

  c.nodes.get('bulkScopeInput').value = 'all';
  const allRequest = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(allRequest.filters.brands), JSON.stringify([]));
  assert.equal(allRequest.filters.priceMin, 301);
  assert.equal(allRequest.filters.priceMax, 600);
});

test('显示和隐藏操作保留价格范围筛选并只隐藏改价动作字段', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkOperationInput').value = 'show';
  c.nodes.get('bulkPriceRangeInput').value = 'custom';
  c.nodes.get('bulkOperationInput').listeners.change();

  assert.equal(c.nodes.get('bulkPriceRangeField').hidden, false);
  assert.equal(c.nodes.get('bulkCustomMinField').hidden, false);
  assert.equal(c.nodes.get('bulkCustomMaxField').hidden, false);
  assert.equal(c.nodes.get('bulkPriceModeField').hidden, true);
  assert.equal(c.nodes.get('bulkAmountField').hidden, true);
});

test('批量请求校验作用范围、自定义区间和改价金额', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkPriceRangeInput').value = 'all';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('bulkSoldInput').value = 'false';
  c.nodes.get('bulkPriceModeInput').value = 'increment';
  c.nodes.get('batchAmountInput').value = '0';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /筛选/);

  c.nodes.get('bulkScopeInput').value = 'selected';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /勾选商品/);

  c.nodes.get('bulkScopeInput').value = 'all';
  c.nodes.get('bulkPriceRangeInput').value = 'custom';
  c.nodes.get('bulkMinPriceInput').value = '500';
  c.nodes.get('bulkMaxPriceInput').value = '300';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /最低价格/);

  c.nodes.get('bulkMinPriceInput').value = '';
  c.nodes.get('bulkMaxPriceInput').value = '';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /必须大于 0/);
  c.nodes.get('bulkPriceModeInput').value = 'fixed_final';
  assert.doesNotThrow(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c));
});

test('修改批量条件会清除旧预览和执行能力', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'old',idempotencyKey:'key'};
    adminState.lastBulkPreview = {changedCount:3};`, c);
  c.nodes.get('openBulkConfirmButton').disabled = false;
  c.nodes.get('exportBulkPreviewButton').disabled = false;
  c.nodes.get('applyBulkButton').disabled = false;

  c.nodes.get('bulkPriceRangeInput').listeners.change();

  assert.equal(vm.runInContext('adminState.lastBulkRequest', c), null);
  assert.equal(vm.runInContext('adminState.lastBulkPreview', c), null);
  assert.equal(c.nodes.get('openBulkConfirmButton').disabled, true);
  assert.equal(c.nodes.get('exportBulkPreviewButton').disabled, true);
  assert.equal(c.nodes.get('applyBulkButton').disabled, true);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /重新生成预览/);

  vm.runInContext(`adminState.lastBulkRequest = {previewId:'new',idempotencyKey:'key'};
    adminState.lastBulkPreview = {changedCount:2};`, c);
  c.nodes.get('adminReviewStateFilterInput').listeners.change();
  assert.equal(vm.runInContext('adminState.lastBulkRequest', c), null);
});

test('批量预览渲染统计、跳过原因和完整导出入口', async () => {
  const c = pageContext('admin.js');
  c.nodes.get('applyBulkButton').disabled = true;
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkPriceRangeInput').value = 'up_to_200';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('bulkSoldInput').value = 'false';
  c.nodes.get('bulkPriceModeInput').value = 'increment';
  c.nodes.get('batchAmountInput').value = '30';
  c.fetch = async (url) => {
    assert.equal(url, '/api/admin/products/bulk-preview');
    return {ok:true,json:async () => ({
      previewId:'preview-1', matchedCount:205, changedCount:202, unchangedCount:1,
      skippedCount:2, skipReasons:{'已售':2},
      priceStats:{minimum:130,maximum:230,totalDelta:6060},
      displayedCount:200,truncated:true,
      items:[{model:'A',brand:'佳能',sourcePrice:90,oldPrice:100,newPrice:130,delta:30,oldVisible:true,newVisible:true,skippedReason:''}],
    })};
  };
  await c.nodes.get('batchPriceForm').listeners.submit({preventDefault() {}});
  const summary = c.nodes.get('bulkPreviewSummary').innerHTML;
  assert.match(summary, /205/);
  assert.match(summary, /202/);
  assert.match(summary, /6060/);
  assert.match(summary, /已售/);
  assert.match(c.nodes.get('bulkPreviewPanel').innerHTML, /导入价 90/);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /前 200 台/);
  assert.equal(c.nodes.get('openBulkConfirmButton').disabled, false);
  assert.equal(c.nodes.get('exportBulkPreviewButton').disabled, false);
  assert.equal(c.nodes.get('applyBulkButton').disabled, false);

  c.nodes.get('exportBulkPreviewButton').listeners.click();
  assert.equal(c.window.location.href, '/api/admin/products/bulk-preview/preview-1/export');
});

test('批量确认提示高风险条件并在关闭后恢复焦点', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'all';
  c.nodes.get('bulkPriceRangeInput').value = 'all';
  c.nodes.get('bulkVisibleInput').value = '';
  c.nodes.get('bulkSoldInput').value = '';
  c.nodes.get('bulkPriceModeInput').value = 'fixed_final';
  c.nodes.get('batchAmountInput').value = '0';
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'preview-1',idempotencyKey:'key-1'};
    adminState.lastBulkPreview = {matchedCount:250,changedCount:230,skippedCount:4};`, c);

  c.nodes.get('openBulkConfirmButton').focus();
  c.nodes.get('openBulkConfirmButton').listeners.click();
  assert.equal(c.nodes.get('bulkConfirmDialog').open, true);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /全部库存/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /230 台/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /已售商品/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /0 元/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /全部库存/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /全部价格/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /展示中和已隐藏/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /未售和已售/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /固定最终价 0 元/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /匹配 250 台/);
  c.nodes.get('bulkConfirmDialog').close('cancel');
  assert.equal(c.document.activeElement, c.nodes.get('openBulkConfirmButton'));
});

test('批量执行区分可重试和失效错误并在模态框内提示', async () => {
  const network = pageContext('admin.js');
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'preview-1',idempotencyKey:'same-key'};
    adminState.lastBulkPreview = {matchedCount:2,changedCount:2,skippedCount:0};`, network);
  network.fetch = async () => { throw new Error('连接断开'); };
  await network.nodes.get('applyBulkButton').listeners.click();
  assert.equal(vm.runInContext('adminState.lastBulkRequest.idempotencyKey', network), 'same-key');
  assert.match(network.nodes.get('bulkConfirmStatus').textContent, /可重试/);
  assert.equal(network.document.activeElement, network.nodes.get('bulkConfirmStatus'));

  const conflict = pageContext('admin.js');
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'preview-2',idempotencyKey:'conflict-key'};
    adminState.lastBulkPreview = {matchedCount:2,changedCount:2,skippedCount:0};`, conflict);
  conflict.fetch = async () => ({ok:false,status:409,text:async () => '版本冲突'});
  await conflict.nodes.get('applyBulkButton').listeners.click();
  assert.equal(vm.runInContext('adminState.lastBulkRequest', conflict), null);
  assert.match(conflict.nodes.get('bulkConfirmStatus').textContent, /重新生成预览/);
  assert.equal(conflict.nodes.get('applyBulkButton').disabled, true);
  assert.equal(conflict.document.activeElement, conflict.nodes.get('bulkConfirmStatus'));

  const expired = pageContext('admin.js');
  expired.nodes.get('adminApp').hidden = false;
  expired.nodes.get('loginPanel').hidden = true;
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'preview-3',idempotencyKey:'expired-key'};
    adminState.lastBulkPreview = {matchedCount:1,changedCount:1,skippedCount:0};`, expired);
  expired.fetch = async () => ({ok:false,status:401,text:async () => '登录过期'});
  await expired.nodes.get('applyBulkButton').listeners.click();
  assert.equal(expired.nodes.get('adminApp').hidden, false);
  assert.match(expired.nodes.get('bulkConfirmStatus').textContent, /重新登录/);
  expired.nodes.get('bulkConfirmDialog').close('cancel');
  assert.equal(expired.nodes.get('adminApp').hidden, true);
  assert.equal(expired.nodes.get('loginPanel').hidden, false);
  assert.equal(expired.document.activeElement, expired.nodes.get('adminPasswordInput'));
});

test('新预览会取消旧请求并维护预览按钮忙碌状态', async () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkPriceRangeInput').value = 'up_to_200';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('bulkSoldInput').value = 'false';
  c.nodes.get('bulkPriceModeInput').value = 'increment';
  c.nodes.get('batchAmountInput').value = '30';
  const pending = [];
  c.fetch = (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('已取消');
      error.name = 'AbortError';
      reject(error);
    });
    pending.push({resolve, signal:options.signal});
  });

  const first = c.nodes.get('batchPriceForm').listeners.submit({preventDefault() {}});
  assert.equal(c.nodes.get('generateBulkPreviewButton').disabled, true);
  assert.match(c.nodes.get('generateBulkPreviewButton').textContent, /生成中/);
  const second = c.nodes.get('batchPriceForm').listeners.submit({preventDefault() {}});
  assert.equal(pending[0].signal.aborted, true);
  pending[1].resolve({ok:true,json:async () => ({previewId:'new',matchedCount:1,changedCount:1,items:[]})});
  await Promise.all([first, second]);
  assert.equal(c.nodes.get('generateBulkPreviewButton').disabled, false);
  assert.equal(vm.runInContext('adminState.lastBulkRequest.previewId', c), 'new');
});

test('批量对话框和禁用按钮具备窄屏安全样式', () => {
  const css = fs.readFileSync(path.join(root, 'showcase.css'), 'utf8');
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*max-height:/s);
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*overscroll-behavior:\s*contain/s);
  assert.match(css, /button:disabled\s*\{[^}]*cursor:\s*not-allowed/s);
});
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
  assert.equal(c.document.activeElement, c.nodes.get('bulkPreviewStatus'));
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
