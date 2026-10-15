const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = process.env.CCD_STATIC_ROOT || path.resolve(__dirname, '../../src/moments_inventory/showcase_web/static');
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
test('筛选元数据返回前保留恢复品牌，成功加载后才清除无效品牌', async () => {
  const c = pageContext('showcase.js');
  vm.runInContext("state.filters = {brands:[]}; state.brands = new Set(['佳能', '索尼']); renderBrands()", c);
  assert.deepEqual(Array.from(vm.runInContext('[...state.brands]', c)), ['佳能', '索尼']);
  c.fetch = async () => ({ ok: true, json: async () => ({ brands: ['佳能'], tags: [], pricePresets: [] }) });
  await vm.runInContext('loadFilters()', c);
  assert.deepEqual(Array.from(vm.runInContext('[...state.brands]', c)), ['佳能']);
});

test('客户口令错误、服务异常和网络失败分别提示且提交期间防止重复请求', async () => {
  const c = pageContext('showcase.js');
  const panel = c.document.getElementById('accessPanel');
  const form = c.document.getElementById('customerAccessForm');
  const error = c.document.getElementById('customerAccessError');
  const submit = { disabled: false };
  form.querySelector = () => submit;
  c.document.getElementById('customerPasswordInput').value = 'secret';
  let resolveFetch;
  let requestCount = 0;
  c.fetch = () => {
    requestCount += 1;
    return new Promise((resolve) => { resolveFetch = resolve; });
  };
  vm.runInContext('showAccessPanel(async () => {})', c);
  const event = { preventDefault() {} };
  const first = form.onsubmit(event);
  assert.equal(submit.disabled, true);
  await form.onsubmit(event);
  assert.equal(requestCount, 1);
  resolveFetch({ ok: false, status: 401 });
  await first;
  assert.match(error.textContent, /口令不正确/);
  assert.equal(submit.disabled, false);
  assert.equal(panel.hidden, false);

  c.fetch = async () => ({ ok: false, status: 503 });
  await form.onsubmit(event);
  assert.match(error.textContent, /服务暂时不可用/);

  c.fetch = async () => { throw new Error('网络断开'); };
  await form.onsubmit(event);
  assert.match(error.textContent, /网络连接失败/);
  assert.equal(submit.disabled, false);
});

test('管理商品最高价为零时保留筛选，非法负数和小数不进入查询', () => {
  const c = pageContext('admin.js');
  c.nodes.get('adminMaxPriceInput').value = '0';
  assert.equal(vm.runInContext('buildAdminProductQuery()', c).get('priceMax'), '0');
  c.nodes.get('adminMaxPriceInput').value = '-1';
  assert.equal(vm.runInContext('buildAdminProductQuery()', c).has('priceMax'), false);
  c.nodes.get('adminMaxPriceInput').value = '1.5';
  assert.equal(vm.runInContext('buildAdminProductQuery()', c).has('priceMax'), false);
  c.nodes.get('adminMaxPriceInput').value = '';
  assert.equal(vm.runInContext('buildAdminProductQuery()', c).has('priceMax'), false);
});

test('库存列表错误区域显示实际恢复提示，409刷新提示不会被固定文案覆盖', async () => {
  const c = pageContext('showcase.js');
  const errorMessage = c.document.getElementById('listErrorMessage');
  vm.runInContext("state.loadError = '已恢复前 400 台，点击显示更多继续'; renderList()", c);
  assert.equal(errorMessage.textContent, '已恢复前 400 台，点击显示更多继续');
  let calls = 0;
  c.fetch = async () => ++calls === 1
    ? { status: 409, ok: false }
    : { status: 200, ok: true, json: async () => ({ products: [], total: 0, hasMore: false, catalogRevision: 'r2' }) };
  await vm.runInContext('loadProductPage()', c);
  assert.match(errorMessage.textContent, /库存刚刚更新/);
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
  assert.match(html, /admin\.js\?v=20261015-import-review-ui/);
  assert.match(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), /showcase\.js\?v=20261015-access-feedback/);
  assert.match(fs.readFileSync(path.join(root, 'product.html'), 'utf8'), /showcase\.js\?v=20261015-access-feedback/);
});

test('旧静态站发布入口明确停止，避免继续构建与当前 SQLite 系统并行的旧站点', () => {
  const script = fs.readFileSync(path.resolve(root, '../../../../publish_showcase_site.bat'), 'utf8');
  assert.match(script, /已停用/);
  assert.match(script, /SQLite/);
  assert.doesNotMatch(script, /set \/p SHOWCASE_PASSWORD/i);
  assert.doesNotMatch(script, /--access-password "%SHOWCASE_PASSWORD%"/i);
});

function pageContext(file) {
  const nodes = new Map();
  const documentListeners = {};
  const windowListeners = {};
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
      addEventListener(event, callback, options) { documentListeners[event] = { callback, options }; },
    },
    window: { addEventListener(event, callback) { windowListeners[event] = callback; }, history: {replaceState() {}}, location: {search:'',pathname:'/',href:''}, setTimeout() {}, scrollTo() {} },
    sessionStorage: {getItem: () => null, removeItem() {}},
    fetch: async () => { throw new Error('未配置请求'); },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'shared/product-utils.js'), 'utf8'), context);
  const source = fs.readFileSync(path.join(root, file), 'utf8').replace('initListPage().catch(showStartupError);', '').replace('initDetailPage().catch(showStartupError);', '');
  vm.runInContext(source, context);
  context.nodes = nodes;
  context.documentListeners = documentListeners;
  context.windowListeners = windowListeners;
  return context;
}

test('管理员删除按钮先展示实体名称并允许取消请求', () => {
  const c = pageContext('admin.js');
  let confirmation = '';
  c.window.confirm = (message) => { confirmation = message; return false; };
  const modelInput = { value: 'PowerShot A80' };
  const row = { querySelector: () => modelInput, querySelectorAll: () => [] };
  const button = {
    classList: { contains: (name) => name === 'admin-delete-product' },
    closest: (selector) => selector.includes('admin-product-row') ? row : button,
  };
  let prevented = false;
  let stopped = false;
  c.documentListeners.click.callback({
    target: button,
    preventDefault() { prevented = true; },
    stopImmediatePropagation() { stopped = true; },
  });
  assert.match(confirmation, /PowerShot A80/);
  assert.equal(prevented, true);
  assert.equal(stopped, true);
});

test('动态管理输入与详情图片按钮具有上下文无障碍名称', () => {
  const admin = fs.readFileSync(path.join(root, 'admin.js'), 'utf8');
  const showcase = fs.readFileSync(path.join(root, 'showcase.js'), 'utf8');
  assert.match(admin, /aria-label="\$\{escapeHtml\(product\.model\).*?型号/);
  assert.match(admin, /aria-label="\$\{escapeHtml\(product\.model\).*?品牌/);
  assert.match(admin, /aria-label="\$\{escapeHtml\(product\.model\).*?展示价格/);
  assert.match(admin, /aria-label="\$\{escapeHtml\(partner\.name\).*?合作方名称/);
  assert.match(admin, /aria-label="\$\{escapeHtml\(album\.title\).*?上传图片/);
  assert.match(showcase, /aria-label="查看\$\{escapeHtml\(title\)}图片，第\$\{index \+ 1\}张"/);
});

test('批量操作执行期间阻止 Esc 关闭确认框并丢失重试状态', () => {
  const c = pageContext('admin.js');
  vm.runInContext('adminState.bulkBusy = true', c);
  let prevented = false;
  c.nodes.get('bulkConfirmDialog').listeners.cancel({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.match(c.nodes.get('bulkConfirmStatus').textContent, /正在执行/);
});

test('样片商品筛选只应用最后一次请求的结果', async () => {
  const c = pageContext('admin.js');
  let resolveMissing;
  let resolveMatched;
  c.nodes.get('sampleMatchStatusFilter').value = 'missing';
  c.fetch = (url) => new Promise((resolve) => {
    if (url.includes('status=missing')) resolveMissing = resolve;
    else resolveMatched = resolve;
  });
  const first = vm.runInContext('loadSampleMatchingProducts()', c);
  c.nodes.get('sampleMatchStatusFilter').value = 'matched';
  const second = vm.runInContext('loadSampleMatchingProducts()', c);
  resolveMatched({ ok: true, json: async () => ({ products: [{ productId: 'new-filter' }] }) });
  await second;
  resolveMissing({ ok: true, json: async () => ({ products: [{ productId: 'old-filter' }] }) });
  await first;
  assert.equal(vm.runInContext('adminState.sampleMatchingProducts[0].productId', c), 'new-filter');
});

test('样片匹配商品列表可分页追加且最后一页隐藏加载按钮', async () => {
  const c = pageContext('admin.js');
  const offsets = [];
  c.nodes.get('sampleMatchStatusFilter').value = 'all';
  c.fetch = async (url) => {
    offsets.push(new URL(url, 'http://local').searchParams.get('offset'));
    const first = offsets.length === 1;
    return { ok: true, json: async () => ({
      products: [{ productId: first ? 'sample-a' : 'sample-b', model: first ? 'A' : 'B', brand: '佳能' }],
      hasMore: first, total: first ? null : 2,
    }) };
  };
  await vm.runInContext('loadSampleMatchingProducts()', c);
  await vm.runInContext('loadSampleMatchingProducts({append:true})', c);
  assert.deepEqual(offsets, ['0', '1']);
  assert.deepEqual(Array.from(vm.runInContext('adminState.sampleMatchingProducts.map((item) => item.productId)', c)), ['sample-a', 'sample-b']);
  assert.equal(c.nodes.get('sampleMatchLoadMoreButton').hidden, true);
});

test('样片候选组可分页追加，旧响应不会覆盖新筛选结果', async () => {
  const c = pageContext('admin.js');
  const offsets = [];
  c.fetch = async (url) => {
    offsets.push(new URL(url, 'http://local').searchParams.get('offset'));
    const first = offsets.length === 1;
    return { ok: true, json: async () => ({ groups: [{ id: first ? 'g1' : 'g2' }], hasMore: first, total: 2 }) };
  };
  await vm.runInContext('loadSampleMatchingGroups()', c);
  await vm.runInContext('loadSampleMatchingGroups({append:true})', c);
  assert.deepEqual(offsets, ['0', '1']);
  assert.deepEqual(Array.from(vm.runInContext('adminState.sampleMatchingGroups.map((item) => item.id)', c)), ['g1', 'g2']);
  assert.equal(c.nodes.get('sampleGroupLoadMoreButton').hidden, true);

  let resolveOld;
  let resolveNew;
  let requestCount = 0;
  c.fetch = (url) => new Promise((resolve) => {
    if (requestCount++ === 0) resolveOld = resolve;
    else resolveNew = resolve;
  });
  const oldRequest = vm.runInContext('loadSampleMatchingGroups()', c);
  const newRequest = vm.runInContext('loadSampleMatchingGroups()', c);
  resolveNew({ ok: true, json: async () => ({ groups: [{ id: 'new' }], hasMore: false, total: 1 }) });
  await newRequest;
  resolveOld({ ok: true, json: async () => ({ groups: [{ id: 'stale' }], hasMore: false, total: 1 }) });
  await oldRequest;
  assert.deepEqual(Array.from(vm.runInContext('adminState.sampleMatchingGroups.map((item) => item.id)', c)), ['new']);
});

test('样片图库可按四十项分页追加且旧查询结果被丢弃', async () => {
  const c = pageContext('admin.js');
  const offsets = [];
  c.fetch = async (url) => {
    offsets.push(new URL(url, 'http://local').searchParams.get('offset'));
    const first = offsets.length === 1;
    return { ok: true, json: async () => ({ assets: [{ path: first ? 'a' : 'b' }], hasMore: first, total: 2 }) };
  };
  await vm.runInContext('searchSampleAssets()', c);
  await vm.runInContext('searchSampleAssets({append:true})', c);
  assert.deepEqual(offsets, ['0', '1']);
  assert.deepEqual(Array.from(vm.runInContext('adminState.sampleAssets.map((item) => item.path)', c)), ['a', 'b']);
  assert.equal(c.nodes.get('sampleAssetLoadMoreButton').hidden, true);

  let resolveOld;
  let resolveNew;
  c.fetch = (url) => new Promise((resolve) => {
    if (url.includes('query=old')) resolveOld = resolve;
    else resolveNew = resolve;
  });
  c.nodes.get('sampleAssetSearchInput').value = 'old';
  const oldRequest = vm.runInContext('searchSampleAssets()', c);
  c.nodes.get('sampleAssetSearchInput').value = 'new';
  const newRequest = vm.runInContext('searchSampleAssets()', c);
  resolveNew({ ok: true, json: async () => ({ assets: [{ path: 'new' }], hasMore: false, total: 1 }) });
  await newRequest;
  resolveOld({ ok: true, json: async () => ({ assets: [{ path: 'old' }], hasMore: false, total: 1 }) });
  await oldRequest;
  assert.deepEqual(Array.from(vm.runInContext('adminState.sampleAssets.map((item) => item.path)', c)), ['new']);
});

test('管理列表刷新后保留其他实体尚未保存的字段草稿', () => {
  const c = pageContext('admin.js');
  const makeControl = (value) => ({
    className: 'section-title', type: 'text', value,
    getAttribute(name) { return name === 'class' ? this.className : null; },
  });
  const originalRow = { dataset: { sectionId: 'section-a' }, querySelectorAll: () => [makeControl('未保存标题')] };
  c.originalRow = originalRow;
  vm.runInContext('rememberManagementRow(originalRow)', c);
  const refreshedControl = makeControl('服务端旧标题');
  const refreshedRow = { dataset: { sectionId: 'section-a' }, querySelectorAll: () => [refreshedControl] };
  c.refreshedRow = refreshedRow;
  vm.runInContext('restoreManagementRow(refreshedRow)', c);
  assert.equal(refreshedControl.value, '未保存标题');
});

test('后台异步写入失败时展示可理解的错误并且不冒报成功', () => {
  const c = pageContext('admin.js');
  const errorPanel = c.document.getElementById('adminActionError');
  let prevented = false;
  c.windowListeners.unhandledrejection({
    reason: Object.assign(new Error('网络断开'), { status: 0 }),
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.match(errorPanel.textContent, /操作失败/);
  assert.match(errorPanel.textContent, /网络断开/);
  assert.equal(errorPanel.hidden, false);
});

test('设置保存失败会清除上一次的成功状态', async () => {
  const c = pageContext('admin.js');
  const status = c.document.getElementById('settingsStatus');
  status.textContent = '已保存';
  c.fetch = async () => ({ ok: false, status: 500, text: async () => '数据库暂时不可用' });
  await assert.rejects(c.nodes.get('settingsForm').listeners.submit({ preventDefault() {} }));
  assert.equal(status.textContent, '');
});

test('样片重建失败后不残留正在处理状态', async () => {
  const c = pageContext('admin.js');
  const status = c.document.getElementById('sampleMatchingStatus');
  c.fetch = async () => ({ ok: false, status: 503, text: async () => '数据库暂时不可用' });
  await assert.rejects(c.nodes.get('rebuildSampleMatchingButton').listeners.click());
  assert.match(status.textContent, /重建失败/);
});

test('同一后台写请求并发触发时合并为一次网络提交', async () => {
  const c = pageContext('admin.js');
  let calls = 0;
  c.fetch = async () => { calls += 1; return { ok: true, json: async () => ({ saved: true }) }; };
  const first = vm.runInContext('requestJson("/api/admin/settings", {method:"PATCH", body:"{}"})', c);
  const second = vm.runInContext('requestJson("/api/admin/settings", {method:"PATCH", body:"{}"})', c);
  assert.deepEqual(await Promise.all([first, second]), [{ saved: true }, { saved: true }]);
  assert.equal(calls, 1);
});

test('重新加载管理设置保留未保存文本，样片专栏选择和相册待上传文件也保留', async () => {
  const c = pageContext('admin.js');
  vm.runInContext("adminState.settingsDraft.set('statementInput', '未保存声明'); adminState.createSectionSelection.add('section-a'); adminState.pendingGalleryFiles.set('album-a', {name:'pending.jpg'}); adminState.sections = [{sectionId:'section-a', title:'精选', active:true}]", c);
  c.fetch = async () => ({ ok: true, json: async () => ({ statementText: '服务器旧值', shopIntroText: '', watermarkText: '星星CCD', inventoryUpdatedAt: '', hasCustomerPassword: false }) });
  await vm.runInContext('loadSettings()', c);
  assert.equal(c.nodes.get('statementInput').value, '未保存声明');
  const picker = c.nodes.get('createSectionPicker');
  picker.querySelectorAll = () => [];
  vm.runInContext('renderCreateSectionPicker()', c);
  assert.match(picker.innerHTML, /value="section-a" checked/);
  const gallery = c.nodes.get('galleryAlbumList');
  gallery.querySelectorAll = () => [];
  vm.runInContext("renderGalleryAlbums([{albumId:'album-a', title:'橱窗', images:[]}])", c);
  assert.match(gallery.innerHTML, /pending\.jpg/);
});

test('登录成功但管理模块加载失败时不误报密码错误，并允许重试模块加载', async () => {
  const c = pageContext('admin.js');
  c.fetch = async (url) => url === '/api/admin/login'
    ? { ok: true, json: async () => ({ ok: true }) }
    : { ok: false, status: 500, text: async () => '模块不可用' };
  await c.nodes.get('loginForm').listeners.submit({ preventDefault() {} });
  assert.match(c.nodes.get('adminStartupStatus').textContent, /管理模块加载失败/);
  assert.doesNotMatch(c.nodes.get('loginError').textContent, /密码错误/);
  assert.equal(c.nodes.get('loginPanel').hidden, true);
  assert.equal(c.nodes.get('adminApp').hidden, false);
  assert.equal(typeof c.nodes.get('retryAdminStartupButton').listeners.click, 'function');
});

test('登录成功后自动恢复导入身份复核 pending 队列', async () => {
  const c = pageContext('admin.js');
  const requests = [];
  c.fetch = async (url) => {
    requests.push(url);
    if (url === '/api/admin/login') return { ok: true, json: async () => ({ ok: true }) };
    if (url === '/api/admin/import-review/batches') return { ok: true, json: async () => [] };
    return { ok: false, status: 500, text: async () => '模块不可用' };
  };
  await c.nodes.get('loginForm').listeners.submit({ preventDefault() {} });
  assert.equal(requests.filter((url) => url === '/api/admin/import-review/batches').length, 1);
});

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
  assert.deepEqual(JSON.parse(JSON.stringify(request)), {
    scope: 'filtered', operation: 'price', priceMode: 'increment', amount: 50,
    productIds: [], filters: {
      query: '', brands: [], visible: true, sold: false, hasBodyImage: null,
      hasSampleImage: null, manualPrice: null, reviewState: '', tags: [],
      sourcePriceMin: 201, sourcePriceMax: 300, displayPriceMin: null, displayPriceMax: null,
    },
  });

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
  assert.equal(intersectedRequest.filters.sourcePriceMin, 301);
  assert.equal(intersectedRequest.filters.sourcePriceMax, 600);
  assert.equal(intersectedRequest.filters.displayPriceMin, 250);
  assert.equal(intersectedRequest.filters.displayPriceMax, 700);

  c.nodes.get('adminMinPriceInput').value = '400';
  vm.runInContext('updateBulkScopeSummary()', c);
  assert.match(c.nodes.get('bulkScopeSummary').textContent, /原价 301～600 元；当前展示价 400～700 元/);

  c.nodes.get('adminMinPriceInput').value = '700';
  const independentRanges = vm.runInContext('buildBulkRequest()', c).filters;
  assert.equal(independentRanges.sourcePriceMin, 301);
  assert.equal(independentRanges.sourcePriceMax, 600);
  assert.equal(independentRanges.displayPriceMin, 700);
  assert.equal(independentRanges.displayPriceMax, 700);

  c.nodes.get('bulkScopeInput').value = 'all';
  const allRequest = vm.runInContext('buildBulkRequest()', c);
  assert.equal(JSON.stringify(allRequest.filters.brands), JSON.stringify([]));
  assert.equal(allRequest.filters.sourcePriceMin, 301);
  assert.equal(allRequest.filters.sourcePriceMax, 600);
  assert.equal(allRequest.filters.displayPriceMin, null);
  assert.equal(allRequest.filters.displayPriceMax, null);
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

test('筛选范围对商品区和批量面板状态条件求交集', () => {
  const c = pageContext('admin.js');
  c.nodes.get('bulkScopeInput').value = 'filtered';
  c.nodes.get('bulkPriceRangeInput').value = 'up_to_200';
  c.nodes.get('batchAmountInput').value = '30';

  c.nodes.get('adminVisibleFilterInput').value = '';
  c.nodes.get('bulkVisibleInput').value = 'true';
  assert.equal(vm.runInContext('buildBulkRequest().filters.visible', c), true);

  c.nodes.get('adminVisibleFilterInput').value = 'false';
  c.nodes.get('bulkVisibleInput').value = '';
  assert.equal(vm.runInContext('buildBulkRequest().filters.visible', c), false);

  c.nodes.get('adminVisibleFilterInput').value = 'true';
  c.nodes.get('bulkVisibleInput').value = 'true';
  assert.equal(vm.runInContext('buildBulkRequest().filters.visible', c), true);

  c.nodes.get('adminVisibleFilterInput').value = 'false';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /展示状态条件没有交集/);

  c.nodes.get('adminVisibleFilterInput').value = '';
  c.nodes.get('bulkVisibleInput').value = 'true';
  c.nodes.get('adminSoldFilterInput').value = '';
  c.nodes.get('bulkSoldInput').value = 'false';
  assert.equal(vm.runInContext('buildBulkRequest().filters.sold', c), false);

  c.nodes.get('adminSoldFilterInput').value = 'false';
  assert.equal(vm.runInContext('buildBulkRequest().filters.sold', c), false);

  c.nodes.get('adminSoldFilterInput').value = 'true';
  assert.throws(() => vm.runInContext('validateBulkRequest(buildBulkRequest())', c), /已售状态条件没有交集/);

  c.nodes.get('bulkScopeInput').value = 'all';
  const allRequest = vm.runInContext('buildBulkRequest()', c);
  assert.equal(allRequest.filters.visible, true);
  assert.equal(allRequest.filters.sold, false);
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
      previewId:'preview-1', expiresAt:'2026-09-25T08:30:00.000Z', operation:'price', matchedCount:205, changedCount:202, unchangedCount:1,
      skippedCount:2, skipReasons:{'已售':2},
      priceStats:{minimum:130,maximum:230,totalDelta:6060},
      displayedCount:200,truncated:true,
      items:[{model:'A',brand:'佳能',sourcePrice:90,oldPrice:100,newPrice:130,delta:30,oldVisible:true,newVisible:true,sold:false,skippedReason:''}],
    })};
  };
  await c.nodes.get('batchPriceForm').listeners.submit({preventDefault() {}});
  const summary = c.nodes.get('bulkPreviewSummary').innerHTML;
  assert.match(summary, /205/);
  assert.match(summary, /202/);
  assert.match(summary, /6060/);
  assert.match(summary, /已售/);
  assert.match(summary, /价格不变/);
  assert.match(c.nodes.get('bulkPreviewPanel').innerHTML, /导入价 90/);
  assert.match(c.nodes.get('bulkPreviewPanel').innerHTML, /未售/);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /前 200 台/);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /2026/);
  assert.equal(c.nodes.get('openBulkConfirmButton').disabled, false);
  assert.equal(c.nodes.get('exportBulkPreviewButton').disabled, false);
  assert.equal(c.nodes.get('applyBulkButton').disabled, false);

  c.nodes.get('exportBulkPreviewButton').listeners.click();
  assert.equal(c.window.location.href, '/api/admin/products/bulk-preview/preview-1/export');
});

test('隐藏预览把未变化统计显示为状态不变并标注已售状态', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`renderBulkPreview({
    operation:'hide', expiresAt:'2026-09-25T08:30:00.000Z', matchedCount:2,
    changedCount:1, unchangedCount:1, skippedCount:0, skipReasons:{},
    priceStats:{minimum:null,maximum:null,totalDelta:0}, displayedCount:2,
    truncated:false, items:[
      {model:'A',brand:'佳能',sourcePrice:100,oldPrice:100,newPrice:100,delta:0,oldVisible:true,newVisible:false,sold:true,skippedReason:''}
    ]
  })`, c);

  assert.match(c.nodes.get('bulkPreviewSummary').innerHTML, /状态不变/);
  assert.doesNotMatch(c.nodes.get('bulkPreviewSummary').innerHTML, /价格不变/);
  assert.match(c.nodes.get('bulkPreviewPanel').innerHTML, /已售/);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /到期/);
});

test('批量预览到期时间无效时显示明确降级文案', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`renderBulkPreview({
    operation:'price', expiresAt:'invalid-date', matchedCount:0,
    changedCount:0, unchangedCount:0, skippedCount:0, skipReasons:{},
    priceStats:{minimum:null,maximum:null,totalDelta:0}, displayedCount:0,
    truncated:false, items:[]
  })`, c);

  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /到期时间不可用/);
  assert.match(c.nodes.get('bulkPreviewStatus').textContent, /15 分钟内/);
});

test('批量预览对商品及跳过原因中的 HTML 做转义', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`renderBulkPreview({
    operation:'price', expiresAt:'2026-09-25T08:30:00.000Z', matchedCount:1,
    changedCount:0, unchangedCount:0, skippedCount:1,
    skipReasons:{'<img src=x onerror=alert(1)>':1},
    priceStats:{minimum:null,maximum:null,totalDelta:0}, displayedCount:1,
    truncated:false, items:[{
      model:'<script>alert(1)</script>', brand:'<b>恶意品牌</b>', sourcePrice:100,
      oldPrice:100, newPrice:100, delta:0, oldVisible:true, newVisible:true,
      sold:false, skippedReason:'<svg onload=alert(1)>'
    }]
  })`, c);

  const summary = c.nodes.get('bulkPreviewSummary').innerHTML;
  const panel = c.nodes.get('bulkPreviewPanel').innerHTML;
  assert.doesNotMatch(summary, /<img src=x/);
  assert.match(summary, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(panel, /<script>|<b>|<svg/);
  assert.match(panel, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(panel, /&lt;b&gt;恶意品牌&lt;\/b&gt;/);
  assert.match(panel, /&lt;svg onload=alert\(1\)&gt;/);
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
    adminState.lastBulkPreview = {matchedCount:250,changedCount:230,skippedCount:4,
      priceStats:{minimum:0,maximum:0,totalDelta:-1000}};`, c);

  c.nodes.get('openBulkConfirmButton').focus();
  c.nodes.get('openBulkConfirmButton').listeners.click();
  assert.equal(c.nodes.get('bulkConfirmDialog').open, true);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /全部库存/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /230 台/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /已售商品/);
  assert.match(c.nodes.get('bulkConfirmWarnings').innerHTML, /0 元/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /全部库存/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /价格筛选：原价不限，当前展示价不限/);
  assert.doesNotMatch(c.nodes.get('bulkConfirmSummary').textContent, /最终价格范围/);
  assert.match(c.nodes.get('bulkConfirmSummary').textContent, /实际修改项新价格范围：0 元/);
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

test('批量提交成功后刷新失败不会回退为执行未确认', async () => {
  const c = pageContext('admin.js');
  vm.runInContext(`adminState.lastBulkRequest = {previewId:'preview-ok',idempotencyKey:'key-ok'};
    adminState.lastBulkPreview = {matchedCount:2,changedCount:2,skippedCount:0};
    loadProducts = async () => { throw new Error('刷新失败'); };
    loadSections = loadDiagnostics = loadOperations = async () => {};`, c);
  c.fetch = async () => ({ok:true,json:async () => ({updatedCount:2})});

  await c.nodes.get('applyBulkButton').listeners.click();

  assert.equal(vm.runInContext('adminState.lastBulkRequest', c), null);
  assert.equal(vm.runInContext('adminState.lastBulkPreview', c), null);
  assert.equal(c.nodes.get('applyBulkButton').disabled, true);
  assert.equal(c.nodes.get('bulkPreviewStatus').textContent, '执行已完成，但数据刷新失败，请重新加载页面');
  assert.doesNotMatch(c.nodes.get('bulkPreviewStatus').textContent, /执行未确认|可重试/);
});

test('批量对话框和禁用按钮具备窄屏安全样式', () => {
  const css = fs.readFileSync(path.join(root, 'showcase.css'), 'utf8');
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*max-height:/s);
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(css, /\.bulk-confirm-dialog\s*\{[^}]*overscroll-behavior:\s*contain/s);
  assert.match(css, /button:disabled\s*\{[^}]*cursor:\s*not-allowed/s);
});

test('后台紧凑列表在窄屏降为单列', () => {
  const css = fs.readFileSync(path.join(root, 'showcase.css'), 'utf8');
  const mediaStart = css.indexOf('@media (max-width: 760px) {');
  const mediaEnd = css.indexOf('/* 搜索进入手机首屏', mediaStart);
  assert.notEqual(mediaStart, -1, '缺少 760px 窄屏媒体查询');
  assert.notEqual(mediaEnd, -1, '无法定位 760px 窄屏媒体查询结尾');
  const mobileCss = css.slice(mediaStart, mediaEnd);
  assert.match(mobileCss, /\.admin-product-row,\s*\.admin-compact-row\s*\{\s*grid-template-columns:\s*1fr;/s);
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
    readProductDraft = () => ({model:'B'});
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

test('保存请求中把输入改回旧值仍会生成基于新版本的可保存草稿', async () => {
  const c = pageContext('admin.js');
  const original = {
    publicId: 'p1', productId: 'p1', model: 'A', brand: '佳能', displayPrice: 100,
    displayCopy: '原文案', shortSellingPoint: '', recommendTags: [], sold: false, rowVersion: 1,
  };
  const updated = { ...original, displayPrice: 110, rowVersion: 2 };
  const fields = new Map([
    ['.admin-model-input', { value: 'A' }], ['.admin-brand-input', { value: '佳能' }],
    ['.admin-price-input', { value: '100' }], ['.admin-copy-input', { value: '原文案' }],
    ['.admin-selling-point-input', { value: '' }], ['.admin-tags-input', { value: '' }],
    ['.admin-sold-input', { checked: false }],
  ]);
  const row = { dataset: { productId: 'p1' }, querySelector: (selector) => fields.get(selector) };
  const button = { disabled: false, textContent: '保存草稿', classList: { contains: (name) => name === 'admin-save-product' }, closest: () => row };
  c.adminProductList = c.nodes.get('adminProductList');
  vm.runInContext(`adminState.products = [${JSON.stringify(original)}];
    adminState.drafts.set('p1', {original:${JSON.stringify(original)},changes:{displayPrice:110}});`, c);
  let resolveSave;
  c.fetch = (url) => url.includes('/products/')
    ? new Promise((resolve) => { resolveSave = resolve; })
    : Promise.resolve({ ok: true, json: async () => ({ sections: [] }) });
  const save = c.adminProductList.listeners.click({ target: button });

  fields.get('.admin-price-input').value = '100';
  vm.runInContext("adminState.drafts.delete('p1')", c);
  resolveSave({ ok: true, json: async () => ({ product: updated }) });
  await save;

  const draft = vm.runInContext("adminState.drafts.get('p1')", c);
  assert.equal(draft.original.rowVersion, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(draft.changes)), { displayPrice: 100 });
});

test('样片文件夹复制不可用时提供可手动复制路径且不显示假成功', async () => {
  const c = pageContext('admin.js');
  c.navigator = {};
  let promptArgs;
  c.window.prompt = (...args) => { promptArgs = args; return null; };
  const target = { dataset: { folderPath: 'samples/canon/ixus' }, classList: { contains: (name) => name === 'sample-copy-folder' } };

  await c.nodes.get('sampleAssetSearchResults').listeners.click({ target });

  assert.deepEqual(promptArgs, ['无法自动复制，请手动复制文件夹路径：', 'samples/canon/ixus']);
  assert.match(c.nodes.get('sampleMatchingStatus').textContent, /请手动复制/);
  assert.doesNotMatch(c.nodes.get('sampleMatchingStatus').textContent, /已复制/);

  c.navigator.clipboard = { writeText: async () => {} };
  await c.nodes.get('sampleAssetSearchResults').listeners.click({ target });
  assert.match(c.nodes.get('sampleMatchingStatus').textContent, /^已复制：/);
});

test('客户剪贴板失败时把完整咨询文案提供给手动复制', async () => {
  const c = pageContext('showcase.js');
  c.navigator = { clipboard: { writeText: async () => { throw new Error('权限拒绝'); } } };
  c.window.isSecureContext = true;
  let promptArgs;
  c.window.prompt = (...args) => { promptArgs = args; return null; };
  c.document.body = { appendChild() {} };
  c.document.createElement = () => ({ value: '', className: '', setAttribute() {}, select() {}, remove() {} });
  c.document.execCommand = () => false;

  const result = await vm.runInContext('copyText("完整商品咨询文案")', c);

  assert.deepEqual(promptArgs, ['自动复制失败，请手动复制以下完整咨询文案：', '完整商品咨询文案']);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), { copied: false, manualFallback: true });
});

test('上传旧图片期间选择的新文件保留，上传成功后不允许重复发送旧文件', async () => {
  const c = pageContext('admin.js');
  const fileA = { name: 'a.jpg' };
  const fileB = { name: 'b.jpg' };
  let selectedFiles = [fileA];
  let inputValue = 'a.jpg';
  const fileInput = {
    get files() { return selectedFiles; },
    set files(value) { selectedFiles = value; },
    get value() { return inputValue; },
    set value(value) { inputValue = value; if (!value) selectedFiles = []; },
    closest: () => row,
    classList: { contains: (name) => name === 'admin-image-file' },
  };
  const status = { textContent: '' };
  const row = { dataset: { productId: 'p1' }, querySelector: (selector) => selector === '.admin-image-file' ? fileInput : status };
  const uploadButton = { disabled: false, classList: { contains: (name) => name === 'admin-upload-image' }, closest: () => row };
  c.FormData = class { append() {} };
  vm.runInContext("adminState.pendingImageFiles.set('p1', {name:'a.jpg'}); loadImages = async () => {}", c);
  let resolveUpload;
  let uploadCount = 0;
  c.fetch = () => {
    uploadCount += 1;
    if (uploadCount === 1) return new Promise((resolve) => { resolveUpload = resolve; });
    return Promise.resolve({ ok: true, json: async () => ({ imageId: 'image-b' }) });
  };
  const click = c.nodes.get('adminProductList').listeners.click;
  const input = c.nodes.get('adminProductList').listeners.input;
  const uploadA = click({ target: uploadButton });
  fileInput.files = [fileB]; fileInput.value = 'b.jpg';
  input({ target: fileInput });
  resolveUpload({ ok: true, json: async () => ({ imageId: 'image-a' }) });
  await uploadA;

  assert.equal(vm.runInContext("adminState.pendingImageFiles.get('p1').name", c), 'b.jpg');
  assert.equal(fileInput.value, 'b.jpg');
  assert.equal(uploadButton.disabled, false);

  await click({ target: uploadButton });
  assert.equal(uploadCount, 2);
  assert.equal(vm.runInContext("adminState.pendingImageFiles.has('p1')", c), false);
  assert.equal(fileInput.value, '');
  await click({ target: uploadButton });
  assert.equal(uploadCount, 2);
});

test('CCD身份复核工作区声明上传、pending恢复、决定与确认控件', () => {
  const html = fs.readFileSync(path.join(root, 'admin.html'), 'utf8');
  for (const id of [
    'importReviewUploadForm', 'importReviewFileInput', 'importReviewScopeInput',
    'importReviewModeInput', 'importReviewCompleteInput', 'importReviewBatchList',
    'importReviewBatchDetail', 'importReviewPendingCount', 'importReviewStatus',
    'importReviewConfirmDialog', 'importReviewConfirmMessage', 'confirmImportReviewAction',
  ]) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /CCD导入身份复核/);
  assert.match(html, /value="incremental"/);
  assert.match(html, /value="full"/);
  assert.match(html, /name="file"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /admin\.js\?v=20261015-import-review-ui/);
});

test('导入身份复核可恢复 pending 批次并渲染来源范围与未决定数量', async () => {
  const c = pageContext('admin.js');
  assert.equal(vm.runInContext('typeof loadImportReviewBatches', c), 'function');
  assert.equal(vm.runInContext('typeof openImportReviewBatch', c), 'function');
  c.fetch = async (url) => {
    assert.equal(url, '/api/admin/import-review/batches');
    return { ok: true, json: async () => [{
      batchId: 'batch-1', sourceScope: 'feed-a', sourceLabel: 'today.xlsx', mode: 'full',
      complete: true, missingCount: 2, parsedRowCount: 3, status: 'pending', createdAt: 'now',
    }] };
  };
  await vm.runInContext('loadImportReviewBatches()', c);
  assert.match(c.nodes.get('importReviewBatchList').innerHTML, /today\.xlsx/);
  c.fetch = async (url) => {
    assert.equal(url, '/api/admin/import-review/batches/batch-1');
    return { ok: true, json: async () => ({
      batchId: 'batch-1', sourceScope: 'feed-a', sourceLabel: 'today.xlsx', mode: 'full',
      complete: true, parsedRowCount: 3, missingCount: 2, status: 'pending',
      result: {warnings:['范围完整，需要检查'], missing_items:[{product_id:'gone-1',model:'X',brand:'B'}]},
      rows: [
        {reviewRowId:'r1',batchId:'batch-1',rowNumber:2,sourceKey:'key-1',decision:null,status:'pending',snapshot:{model:'IXUS',brand:'佳能'},errors:['重复候选'],recommendation:{product_id:'p1',model:'IXUS',brand:'佳能',reason:'source_key'},candidates:[]},
        {reviewRowId:'r2',batchId:'batch-1',rowNumber:3,sourceKey:'',decision:'skip',status:'pending',snapshot:{model:'A'},errors:[],candidates:[]},
      ],
    }) };
  };
  await vm.runInContext("openImportReviewBatch('batch-1')", c);
  assert.match(c.nodes.get('importReviewBatchDetail').innerHTML, /IXUS/);
  assert.match(c.nodes.get('importReviewBatchDetail').innerHTML, /key-1/);
  assert.match(c.nodes.get('importReviewBatchDetail').innerHTML, /范围完整，需要检查/);
  assert.match(c.nodes.get('importReviewPendingCount').textContent, /1/);
});

test('复核决定使用Excel行号，提交保存同一幂等键且409时刷新批次', async () => {
  const c = pageContext('admin.js');
  assert.equal(vm.runInContext('typeof saveImportReviewDecision', c), 'function');
  assert.equal(vm.runInContext('typeof commitImportReviewBatch', c), 'function');
  vm.runInContext("adminState.importReviewActiveBatch = {batchId:'batch-1',status:'pending'}", c);
  const requests = [];
  c.fetch = async (url, options = {}) => {
    requests.push({url, options});
    if (options.method === 'PUT') return { ok: true, json: async () => ({ reviewRowId:'row-1', rowNumber:8, decision:'link', productId:'p2' }) };
    if (url.endsWith('/commit')) return { ok: false, status: 409, text: async () => 'stale' };
    if (url.endsWith('/batches/batch-1')) return { ok: true, json: async () => ({ batchId:'batch-1',status:'pending',rows:[] }) };
    return { ok: true, json: async () => [] };
  };
  await vm.runInContext("saveImportReviewDecision(8, {decision:'link',productId:'p2'})", c);
  assert.equal(requests[0].url, '/api/admin/import-review/batches/batch-1/rows/8');
  assert.deepEqual(JSON.parse(requests[0].options.body), {decision:'link',productId:'p2'});
  await vm.runInContext("commitImportReviewBatch('batch-1')", c);
  const commit = requests.find((request) => request.url.endsWith('/commit'));
  assert.equal(commit.options.headers['Content-Type'], 'application/json');
  assert.match(commit.options.body, /idempotencyKey/);
  assert.equal(requests.some((request) => request.url.endsWith('/batches/batch-1')), true);
  assert.match(c.nodes.get('importReviewStatus').textContent, /冲突|已刷新/);
  await vm.runInContext("commitImportReviewBatch('batch-1')", c);
  const retries = requests.filter((request) => request.url.endsWith('/commit'));
  assert.equal(JSON.parse(retries[0].options.body).idempotencyKey, JSON.parse(retries[1].options.body).idempotencyKey);
});

test('复核批次和商品用户文本经escapeHtml后再写入页面', () => {
  const c = pageContext('admin.js');
  vm.runInContext(`renderImportReviewBatch({
    batchId:'batch-<1>',sourceScope:'<feed>',sourceLabel:'<file>.xlsx',mode:'incremental',
    status:'pending',parsedRowCount:1,missingCount:0,complete:false,result:{},
    rows:[{reviewRowId:'r1',batchId:'batch-1',rowNumber:2,sourceKey:'<script>',status:'pending',
      snapshot:{model:'<img src=x>',brand:'佳能'},errors:['<bad>'],candidates:[]}]
  })`, c);
  const html = c.nodes.get('importReviewBatchDetail').innerHTML;
  assert.doesNotMatch(html, /<script>|<img src=x>|<bad>/);
  assert.match(html, /&lt;script&gt;/);
});

test('放弃批次先打开二次确认，确认后才发送DELETE', async () => {
  const c = pageContext('admin.js');
  vm.runInContext("adminState.importReviewBatches = [{batchId:'discard-1',sourceLabel:'today.xlsx',status:'pending'}]", c);
  const requests = [];
  c.fetch = async (url, options = {}) => {
    requests.push({url, options});
    if (options.method === 'DELETE') return {ok:true,json:async () => ({batchId:'discard-1',status:'discarded'})};
    if (url.endsWith('/batches/discard-1')) return {ok:true,json:async () => ({batchId:'discard-1',sourceLabel:'today.xlsx',sourceScope:'feed-a',mode:'incremental',status:'discarded',rows:[]})};
    return {ok:true,json:async () => []};
  };
  vm.runInContext("openImportReviewConfirmation({kind:'discard',batch:adminState.importReviewBatches[0]})", c);
  assert.equal(c.nodes.get('importReviewConfirmDialog').open, true);
  assert.match(c.nodes.get('importReviewConfirmMessage').textContent, /today\.xlsx/);
  assert.equal(requests.length, 0);
  await c.nodes.get('confirmImportReviewAction').listeners.click();
  assert.equal(requests.some((request) => request.options.method === 'DELETE'), true);
});
