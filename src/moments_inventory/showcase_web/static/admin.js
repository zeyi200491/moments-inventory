const { productKey, imageUrl, changedFields } = ShowcaseUtils;
const loginPanel = document.getElementById("loginPanel");
const adminApp = document.getElementById("adminApp");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const adminProductList = document.getElementById("adminProductList");
const partnerList = document.getElementById("partnerList");
const sectionList = document.getElementById("sectionList");
const createSectionPicker = document.getElementById("createSectionPicker");
const galleryAlbumList = document.getElementById("galleryAlbumList");
const purchaseStepList = document.getElementById("purchaseStepList");
const adminProductSearchInput = document.getElementById("adminProductSearchInput");
const adminProductCount = document.getElementById("adminProductCount");
const adminLoadMoreButton = document.getElementById("adminLoadMoreButton");
const bulkPreviewPanel = document.getElementById("bulkPreviewPanel");
const applyBulkButton = document.getElementById("applyBulkButton");
const sampleMatchingSummary = document.getElementById("sampleMatchingSummary");
const sampleMatchProductList = document.getElementById("sampleMatchProductList");
const sampleMatchGroupList = document.getElementById("sampleMatchGroupList");
const sampleAssetSearchResults = document.getElementById("sampleAssetSearchResults");
const sampleMatchingStatus = document.getElementById("sampleMatchingStatus");
const adminState = {
  products: [],
  sections: [],
  galleryAlbums: [],
  purchaseSteps: [],
  sampleMatchingProducts: [],
  sampleMatchingGroups: [],
  sampleAssets: [],
  sectionSearchResults: {},
  productQuery: "",
  selectedProductIds: new Set(),
  visibleProductCount: 80,
  productTotal: 0,
  productHasMore: false,
  lastBulkRequest: null,
  drafts: new Map(),
  productRequestId: 0,
  productController: null,
  productLoading: false,
  bulkBusy: false,
  previewRequestId: 0,
  undoKeys: new Map(),
  pendingImageFiles: new Map(),
};

const ADMIN_PRODUCT_PAGE_SIZE = 80;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    if (response.status === 401 && url !== "/api/admin/login") {
      adminApp.hidden = true;
      loginPanel.hidden = false;
      loginError.textContent = "登录已过期，请重新登录；草稿和待上传文件仍保留";
      loginError.hidden = false;
    }
    const error = new Error(await response.text());
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function tagsToInput(tags) {
  return Array.isArray(tags) ? tags.join(",") : "";
}

function inputToTags(value) {
  return String(value || "")
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function csvInputValue(id) {
  return document.getElementById(id)?.value.trim() || "";
}

function booleanSelectValue(id) {
  const value = document.getElementById(id)?.value ?? "";
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function numberInputValue(id) {
  const value = Number(document.getElementById(id)?.value || "");
  return Number.isFinite(value) && value > 0 ? value : null;
}

function collectAdminFilters() {
  return {
    query: csvInputValue("adminProductSearchInput"),
    brands: inputToTags(csvInputValue("adminBrandFilterInput")),
    priceMin: numberInputValue("adminMinPriceInput"),
    priceMax: numberInputValue("adminMaxPriceInput"),
    visible: booleanSelectValue("adminVisibleFilterInput"),
    sold: booleanSelectValue("adminSoldFilterInput"),
    hasBodyImage: booleanSelectValue("adminBodyImageFilterInput"),
    hasSampleImage: booleanSelectValue("adminSampleImageFilterInput"),
    manualPrice: booleanSelectValue("adminManualPriceFilterInput"),
    reviewState: csvInputValue("adminReviewStateFilterInput"),
    tags: inputToTags(csvInputValue("adminTagFilterInput")),
  };
}

function buildAdminProductQuery(offset = 0) {
  const filters = collectAdminFilters();
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.brands.length) params.set("brands", filters.brands.join(","));
  if (filters.priceMin !== null) params.set("priceMin", String(filters.priceMin));
  if (filters.priceMax !== null) params.set("priceMax", String(filters.priceMax));
  if (filters.visible !== null) params.set("visible", String(filters.visible));
  if (filters.sold !== null) params.set("sold", String(filters.sold));
  if (filters.hasBodyImage !== null) params.set("hasBodyImage", String(filters.hasBodyImage));
  if (filters.hasSampleImage !== null) params.set("hasSampleImage", String(filters.hasSampleImage));
  if (filters.manualPrice !== null) params.set("manualPrice", String(filters.manualPrice));
  if (filters.reviewState) params.set("reviewState", filters.reviewState);
  if (filters.tags.length) params.set("tags", filters.tags.join(","));
  params.set("limit", String(ADMIN_PRODUCT_PAGE_SIZE));
  params.set("offset", String(offset));
  return params;
}

function clearAdminFilters() {
  for (const id of [
    "adminProductSearchInput",
    "adminBrandFilterInput",
    "adminMinPriceInput",
    "adminMaxPriceInput",
    "adminTagFilterInput",
  ]) {
    const input = document.getElementById(id);
    if (input) input.value = "";
  }
  for (const id of [
    "adminVisibleFilterInput",
    "adminSoldFilterInput",
    "adminBodyImageFilterInput",
    "adminSampleImageFilterInput",
    "adminManualPriceFilterInput",
    "adminReviewStateFilterInput",
  ]) {
    const input = document.getElementById(id);
    if (input) input.value = "";
  }
  adminState.visibleProductCount = ADMIN_PRODUCT_PAGE_SIZE;
  adminState.selectedProductIds = new Set();
  loadProducts();
}

function renderAdminProducts() {
  const products = adminState.products.map((product) => ({ ...product, ...(adminState.drafts.get(productKey(product))?.changes || {}) }));
  adminProductList.innerHTML = products.map((product) => `
    <article class="admin-product-row" data-product-id="${escapeHtml(productKey(product))}" data-visible="${product.visible ? "true" : "false"}">
      <label class="check-field">
        <input class="admin-product-select" type="checkbox" ${adminState.selectedProductIds.has(productKey(product)) ? "checked" : ""}>
        <span>选择</span>
      </label>
      <div>
        <input class="admin-model-input" value="${escapeHtml(product.model)}">
        <div class="meta-row">
          ${product.visible ? "展示中" : "已隐藏"} · ${product.sold ? "已售" : "未售"} ·
          ${product.hasBodyImage ? "有机身图" : "无机身图"} ·
          ${product.hasSampleImage ? "有出片图" : "无出片图"} ·
          ${product.manualPrice ? "已改价" : "未改价"} ·
          ${product.reviewState === "missing" ? "来源缺失待复核" : "来源正常"}
        </div>
      </div>
      <input class="admin-brand-input" value="${escapeHtml(product.brand)}">
      <input class="admin-price-input" type="number" min="0" value="${product.displayPrice}">
      <span class="status-text">来源价：${product.sourceDisplayPrice ?? 0}</span>
      <button class="secondary-button admin-reset-override" data-reset-field="price" type="button" ${product.priceOverridden ? "" : "disabled"}>价格跟随来源</button>
      <button class="admin-save-product" type="button">保存</button>
      <button class="admin-discard-draft" type="button">放弃草稿并刷新</button>
      <button class="admin-toggle-visible" type="button">${product.visible ? "隐藏" : "显示"}</button>
      <span class="status-text">来源状态：${product.sourceVisible ? "展示" : "隐藏"}</span>
      <button class="secondary-button admin-reset-override" data-reset-field="visibility" type="button" ${product.visibilityOverridden ? "" : "disabled"}>展示状态跟随来源</button>
      <button class="admin-delete-product" type="button">删除</button>
      <div class="admin-marketing-tools">
        <label class="field">
          <span>一句短卖点</span>
          <input class="admin-selling-point-input" value="${escapeHtml(product.shortSellingPoint || "")}">
        </label>
        <label class="field">
          <span>推荐标签</span>
          <input class="admin-tags-input" value="${escapeHtml(tagsToInput(product.recommendTags))}" placeholder="新手推荐,氛围感">
        </label>
        <label class="check-field">
          <input class="admin-sold-input" type="checkbox" ${product.sold ? "checked" : ""}>
          <span>已售</span>
        </label>
        <label class="field field-wide">
          <span>展示文案</span>
          <textarea class="admin-copy-input">${escapeHtml(product.displayCopy || "")}</textarea>
          <span class="status-text">来源文案：${escapeHtml(product.sourceDisplayCopy || "")}</span>
          <button class="secondary-button admin-reset-override" data-reset-field="copy" type="button" ${product.copyOverridden ? "" : "disabled"}>文案跟随来源</button>
        </label>
        <label class="field field-wide">
          <span>绑定出片图文件夹</span>
          <input class="admin-sample-folder-input" placeholder="例如：佳能/ixus 80">
        </label>
        <button class="admin-bind-sample-folder" type="button">绑定出片图</button>
      </div>
      <div class="admin-image-tools">
        <input class="admin-image-file" type="file" accept="image/jpeg,image/png,image/webp">
        <span class="admin-pending-file status-text">${escapeHtml(adminState.pendingImageFiles.get(productKey(product))?.name || "")}</span>
        <button class="admin-upload-image" type="button">上传图片</button>
        <button class="admin-load-images" type="button">查看图片</button>
        <div class="admin-image-list"></div>
      </div>
    </article>
  `).join("");
  if (adminProductCount) {
    adminProductCount.textContent = `${products.length} / ${adminState.productTotal} 台商品`;
  }
  if (adminLoadMoreButton) {
    adminLoadMoreButton.hidden = !adminState.productHasMore;
  }
}

async function loadProducts({ append = false } = {}) {
  if (append && adminState.productLoading) return;
  if (!append) adminState.productController?.abort();
  const requestId = ++adminState.productRequestId;
  const controller = new AbortController();
  adminState.productController = controller;
  adminState.productLoading = true;
  if (adminLoadMoreButton) adminLoadMoreButton.disabled = true;
  try {
    const offset = append ? adminState.products.length : 0;
    const data = await requestJson(`/api/admin/products?${buildAdminProductQuery(offset)}`, { signal: controller.signal });
    if (requestId !== adminState.productRequestId) return;
    const incoming = Array.isArray(data.products) ? data.products : [];
    const known = new Set(adminState.products.map(productKey));
    const added = incoming.filter((product) => !known.has(productKey(product)));
    adminState.products = append ? [...adminState.products, ...added] : incoming;
    adminState.productTotal = Number(data.total ?? adminState.products.length);
    adminState.productHasMore = Boolean(data.hasMore) && (append ? added.length > 0 : incoming.length > 0);
    renderAdminProducts();
  } catch (error) {
    if (error.name !== "AbortError" && requestId === adminState.productRequestId) adminProductCount.textContent = "加载失败，请重新筛选或点击加载更多重试";
  } finally {
    if (requestId === adminState.productRequestId) {
      adminState.productLoading = false;
      if (adminLoadMoreButton) adminLoadMoreButton.disabled = false;
    }
  }
}

function readProductDraft(row) {
  return {
    model: row.querySelector(".admin-model-input").value.trim(),
    brand: row.querySelector(".admin-brand-input").value.trim(),
    displayPrice: Number(row.querySelector(".admin-price-input").value || 0),
    displayCopy: row.querySelector(".admin-copy-input").value.trim(),
    shortSellingPoint: row.querySelector(".admin-selling-point-input").value.trim(),
    recommendTags: inputToTags(row.querySelector(".admin-tags-input").value),
    sold: row.querySelector(".admin-sold-input").checked,
  };
}

adminProductList.addEventListener("input", (event) => {
  const row = event.target.closest(".admin-product-row");
  if (!row || event.target.classList.contains("admin-product-select")) return;
  if (event.target.classList.contains("admin-image-file")) {
    const file = event.target.files[0];
    if (file) adminState.pendingImageFiles.set(row.dataset.productId, file);
    else adminState.pendingImageFiles.delete(row.dataset.productId);
    row.querySelector(".admin-pending-file").textContent = file?.name || "";
    return;
  }
  const key = row.dataset.productId;
  const existing = adminState.drafts.get(key);
  const original = existing?.original || adminState.products.find((product) => productKey(product) === key);
  if (!original) return;
  const changes = changedFields(original, readProductDraft(row));
  if (Object.keys(changes).length) adminState.drafts.set(key, { original, changes });
  else adminState.drafts.delete(key);
  row.querySelector(".admin-save-product").textContent = Object.keys(changes).length ? "保存草稿" : "保存";
});
window.addEventListener("beforeunload", (event) => {
  if (!adminState.drafts.size && !adminState.pendingImageFiles.size) return;
  event.preventDefault();
  event.returnValue = "";
});

async function loadSettings() {
  const settings = await requestJson("/api/admin/settings");
  document.getElementById("statementInput").value = settings.statementText || "";
  document.getElementById("shopIntroInput").value = settings.shopIntroText || "";
  document.getElementById("watermarkInput").value = settings.watermarkText || "星星CCD";
  document.getElementById("inventoryUpdatedInput").value = settings.inventoryUpdatedAt || "";
  document.getElementById("customerPasswordAdminInput").placeholder = settings.hasCustomerPassword
    ? "已设置，留空则不修改"
    : "还未设置客户口令";
}

function renderPartners(partners) {
  partnerList.innerHTML = partners.map((partner) => `
    <article class="partner-admin-row" data-partner-id="${escapeHtml(partner.partnerId)}">
      <input class="partner-name" value="${escapeHtml(partner.name)}">
      <input class="partner-note" value="${escapeHtml(partner.note)}">
      <input class="partner-sort" type="number" min="0" value="${partner.sortOrder}">
      <label class="check-field">
        <input class="partner-active" type="checkbox" ${partner.active ? "checked" : ""}>
        <span>启用</span>
      </label>
      <button class="partner-save" type="button">保存</button>
      <button class="partner-delete" type="button">删除</button>
    </article>
  `).join("");
}

async function loadPartners() {
  const partners = await requestJson("/api/admin/partners");
  renderPartners(Array.isArray(partners) ? partners : []);
}

function renderCreateSectionPicker() {
  if (!createSectionPicker) return;
  const sections = Array.isArray(adminState.sections) ? adminState.sections : [];
  createSectionPicker.innerHTML = sections.length ? sections.map((section) => `
    <label class="section-choice">
      <input class="create-section-checkbox" type="checkbox" value="${escapeHtml(section.sectionId)}">
      <span>${escapeHtml(section.title)}${section.active ? "" : "（隐藏）"}</span>
    </label>
  `).join("") : `<p class="empty-admin-text">还没有可加入的专栏</p>`;
}

function renderSectionProductSearchResults(section, products) {
  const existingProductIds = new Set(
    (Array.isArray(section.items) ? section.items : []).map((item) => item.productId)
  );
  if (!Array.isArray(products) || products.length === 0) {
    return `<p class="empty-admin-text">还没有搜索结果</p>`;
  }
  return products.map((product) => {
    const added = existingProductIds.has(product.productId);
    const cover = (product.coverImageUrl || product.coverImagePath)
      ? `<img src="${escapeHtml(imageUrl(product.coverImageUrl || product.coverImagePath))}" alt="">`
      : `<span class="section-result-placeholder">无图</span>`;
    return `
      <div class="section-product-result" data-product-id="${escapeHtml(productKey(product))}">
        <div class="section-product-result-cover">${cover}</div>
        <div class="section-product-result-main">
          <strong>${escapeHtml(product.model)}</strong>
          <span>${escapeHtml(product.brand)} · ${product.displayPrice || 0}元 · ${product.visible ? "展示中" : "已隐藏"} · ${product.sold ? "已售" : "未售"}</span>
        </div>
        <button class="section-add-search-item" type="button" ${added ? "disabled" : ""}>${added ? "已加入" : "加入专栏"}</button>
      </div>
    `;
  }).join("");
}

async function searchSectionProducts(sectionRow) {
  const sectionId = sectionRow.dataset.sectionId;
  const params = new URLSearchParams();
  const query = sectionRow.querySelector(".section-product-search-input").value.trim();
  const brand = sectionRow.querySelector(".section-product-brand-input").value.trim();
  const minPrice = Number(sectionRow.querySelector(".section-product-min-price").value || "");
  const maxPrice = Number(sectionRow.querySelector(".section-product-max-price").value || "");
  if (query) params.set("query", query);
  if (brand) params.set("brands", brand);
  if (Number.isFinite(minPrice) && minPrice > 0) params.set("priceMin", String(minPrice));
  if (Number.isFinite(maxPrice) && maxPrice > 0) params.set("priceMax", String(maxPrice));
  params.set("limit", "12");
  params.set("offset", "0");
  const data = await requestJson(`/api/admin/products?${params.toString()}`);
  const products = Array.isArray(data.products) ? data.products : [];
  adminState.sectionSearchResults[sectionId] = products;
  const section = adminState.sections.find((item) => item.sectionId === sectionId) || { items: [] };
  sectionRow.querySelector(".section-product-search-results").innerHTML =
    renderSectionProductSearchResults(section, products);
}

function collectCreateSectionIds() {
  return Array.from(document.querySelectorAll("#createSectionPicker .create-section-checkbox:checked"))
    .map((input) => input.value)
    .filter(Boolean);
}

function renderSections(sections) {
  sectionList.innerHTML = sections.map((section) => {
    const items = Array.isArray(section.items) ? section.items : [];
    const searchResults = adminState.sectionSearchResults[section.sectionId] || [];
    const itemHtml = items.length ? items.map((item) => {
      const product = item.product || {};
      const productLabel = product.model
        ? `${product.model} · ${product.brand || ""} · ${product.displayPrice || 0}元`
        : item.productId;
      return `
        <div class="section-item-row" data-item-id="${escapeHtml(item.itemId)}">
          <span>${escapeHtml(productLabel)}</span>
          <input class="section-item-note" value="${escapeHtml(item.recommendNote || "")}" placeholder="专区内推荐语">
          <input class="section-item-sort" type="number" min="0" value="${item.sortOrder || 0}">
          <button class="section-item-save" type="button">保存</button>
          <button class="section-item-delete" type="button">移除</button>
        </div>
      `;
    }).join("") : `<p class="empty-admin-text">这个专栏还没有商品</p>`;

    return `
      <article class="section-admin-row" data-section-id="${escapeHtml(section.sectionId)}">
        <div class="section-admin-main">
          <input class="section-title" value="${escapeHtml(section.title)}">
          <input class="section-subtitle" value="${escapeHtml(section.subtitle || "")}" placeholder="专栏说明">
          <input class="section-sort" type="number" min="0" value="${section.sortOrder || 0}">
          <label class="check-field">
            <input class="section-active" type="checkbox" ${section.active ? "checked" : ""}>
            <span>首页展示</span>
          </label>
          <button class="section-save" type="button">保存专栏</button>
          <button class="section-delete" type="button">删除专栏</button>
        </div>
        <div class="section-item-editor section-search-editor">
          <input class="section-product-search-input" type="search" placeholder="搜索型号、品牌、文案">
          <input class="section-product-brand-input" placeholder="品牌">
          <input class="section-product-min-price" type="number" min="0" placeholder="最低价">
          <input class="section-product-max-price" type="number" min="0" placeholder="最高价">
          <input class="section-new-note" placeholder="专区内推荐语">
          <input class="section-new-sort" type="number" min="0" value="0">
          <button class="section-product-search-button" type="button">搜索商品</button>
        </div>
        <div class="section-product-search-results">${renderSectionProductSearchResults(section, searchResults)}</div>
        <div class="section-item-list">${itemHtml}</div>
      </article>
    `;
  }).join("");
}

async function loadSections() {
  const data = await requestJson("/api/admin/sections");
  adminState.sections = Array.isArray(data.sections) ? data.sections : [];
  renderSections(adminState.sections);
  renderCreateSectionPicker();
}

function renderPurchaseStepsAdmin(steps) {
  if (!purchaseStepList) return;
  purchaseStepList.innerHTML = steps.length ? steps.map((step) => `
    <article class="purchase-step-admin-row" data-step-id="${escapeHtml(step.stepId)}">
      <input class="purchase-step-title" value="${escapeHtml(step.title)}" placeholder="步骤标题">
      <input class="purchase-step-description" value="${escapeHtml(step.description || "")}" placeholder="步骤说明">
      <input class="purchase-step-sort" type="number" min="0" value="${step.sortOrder || 0}">
      <label class="check-field">
        <input class="purchase-step-visible" type="checkbox" ${step.isVisible ? "checked" : ""}>
        <span>客户页展示</span>
      </label>
      <button class="purchase-step-save" type="button">保存</button>
      <button class="purchase-step-delete" type="button">删除</button>
    </article>
  `).join("") : `<p class="empty-admin-text">还没有买前流程步骤</p>`;
}

async function loadPurchaseStepsAdmin() {
  const data = await requestJson("/api/admin/purchase-steps");
  adminState.purchaseSteps = Array.isArray(data.steps) ? data.steps : [];
  renderPurchaseStepsAdmin(adminState.purchaseSteps);
}

function renderGalleryAlbums(albums) {
  if (!galleryAlbumList) return;
  galleryAlbumList.innerHTML = albums.length ? albums.map((album) => {
    const images = Array.isArray(album.images) ? album.images : [];
    const imageHtml = images.length ? images.map((image) => `
      <div class="gallery-image-row" data-image-id="${escapeHtml(image.imageId)}">
        <img src="${escapeHtml(imageUrl(image.imageUrl || image.imagePath))}" alt="">
        <input class="gallery-image-caption" value="${escapeHtml(image.caption || "")}" placeholder="图片说明">
        <input class="gallery-image-sort" type="number" min="0" value="${image.sortOrder || 0}">
        <label class="check-field">
          <input class="gallery-image-visible" type="checkbox" ${image.isVisible ? "checked" : ""}>
          <span>展示</span>
        </label>
        <button class="gallery-image-save" type="button">保存</button>
        <button class="gallery-image-up" type="button">上移</button>
        <button class="gallery-image-down" type="button">下移</button>
        <button class="gallery-image-delete" type="button">删除</button>
      </div>
    `).join("") : `<p class="empty-admin-text">这个相册还没有图片</p>`;

    return `
      <article class="gallery-admin-row" data-album-id="${escapeHtml(album.albumId)}">
        <div class="gallery-admin-main">
          <input class="gallery-title" value="${escapeHtml(album.title)}">
          <input class="gallery-description" value="${escapeHtml(album.description || "")}" placeholder="相册说明">
          <input class="gallery-sort" type="number" min="0" value="${album.sortOrder || 0}">
          <label class="check-field">
            <input class="gallery-visible" type="checkbox" ${album.isVisible ? "checked" : ""}>
            <span>客户页展示</span>
          </label>
          <button class="gallery-save" type="button">保存相册</button>
          <button class="gallery-delete" type="button">删除相册</button>
        </div>
        <div class="gallery-image-uploader">
          <input class="gallery-image-file" type="file" accept="image/jpeg,image/png,image/webp">
          <input class="gallery-image-new-caption" placeholder="图片说明">
          <label class="check-field">
            <input class="gallery-image-new-visible" type="checkbox" checked>
            <span>上传后展示</span>
          </label>
          <button class="gallery-upload-image" type="button">上传图片</button>
        </div>
        <div class="gallery-image-list">${imageHtml}</div>
      </article>
    `;
  }).join("") : `<p class="empty-admin-text">还没有店铺橱窗相册</p>`;
}

async function loadGalleryAlbums() {
  const data = await requestJson("/api/admin/gallery/albums");
  adminState.galleryAlbums = Array.isArray(data.albums) ? data.albums : [];
  renderGalleryAlbums(adminState.galleryAlbums);
}

function renderDiagnostics(data) {
  const panel = document.getElementById("diagnosticsPanel");
  if (!panel) return;
  const counts = data?.counts || {};
  panel.innerHTML = [
    ["价格为0", counts.priceZero || 0],
    ["品牌通用", counts.genericBrand || 0],
    ["无机身图", counts.missingBodyImage || 0],
    ["无出片图", counts.missingSampleImage || 0],
    ["无文案", counts.missingCopy || 0],
    ["型号重复", counts.duplicateModel || 0],
  ].map(([label, value]) => `
    <div class="admin-stat-card">
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(label)}</span>
    </div>
  `).join("");
}

async function loadDiagnostics() {
  renderDiagnostics(await requestJson("/api/admin/diagnostics"));
}

async function loadImportReports() {
  const data = await requestJson("/api/admin/import-reports");
  const target = document.getElementById("importReportList");
  if (!target) return;
  const reports = Array.isArray(data.reports) ? data.reports : [];
  target.innerHTML = reports.length ? reports.map((report) => `
    <div class="admin-compact-row">
      <strong>${escapeHtml(report.importedAt)}</strong>
      <span>新增 ${report.insertedCount} · 更新 ${report.updatedCount} · 缺失 ${report.missingCount} · 未匹配 ${report.unmatchedCount} · 图片缺失 ${report.missingImageCount}</span>
    </div>
  `).join("") : `<p class="empty-admin-text">还没有导入报告</p>`;
}

async function loadOperations() {
  const data = await requestJson("/api/admin/operations");
  const target = document.getElementById("operationList");
  if (!target) return;
  const operations = Array.isArray(data.operations) ? data.operations : [];
  target.innerHTML = operations.length ? operations.map((operation) => `
    <div class="admin-compact-row" data-operation-id="${escapeHtml(operation.operationId)}" data-operation-type="${escapeHtml(operation.operationType)}" data-undone="${operation.undoneAt ? "true" : "false"}">
      <strong>${escapeHtml(operation.summary)}</strong>
      <span>${escapeHtml(operation.createdAt)}${operation.undoneAt ? " · 已撤销" : ""}</span>
      ${operation.operationType !== "undo" && !operation.undoneAt ? `<button class="undo-operation" type="button">撤销这次操作</button>` : ""}
    </div>
  `).join("") : `<p class="empty-admin-text">还没有操作记录</p>`;
}

function renderSampleMatchingSummary(summary) {
  if (!sampleMatchingSummary) return;
  sampleMatchingSummary.innerHTML = `
    <div class="admin-stat-card">
      <strong>${Number(summary.totalProducts || 0)}</strong>
      <span>库存总数</span>
    </div>
    <div class="admin-stat-card">
      <strong>${Number(summary.matchedProductCount || 0)}</strong>
      <span>已匹配出片图</span>
    </div>
    <div class="admin-stat-card">
      <strong>${Number(summary.missingProductCount || 0)}</strong>
      <span>未匹配库存</span>
    </div>
    <div class="admin-stat-card">
      <strong>${Number(summary.lowConfidenceProductCount || 0)}</strong>
      <span>待人工确认</span>
    </div>
    <div class="admin-stat-card">
      <strong>${Number(summary.assetModelCount || 0)}</strong>
      <span>图库型号</span>
    </div>
    <div class="admin-stat-card">
      <strong>${Number(summary.coverageRate || 0).toFixed(1)}%</strong>
      <span>出片图覆盖率</span>
    </div>
  `;
}

function sampleMatchStatusLabel(status) {
  if (status === "matched") return "已匹配";
  if (status === "low_confidence") return "待确认";
  if (status === "auto_matched") return "可自动匹配";
  return "未匹配";
}

function renderSampleMatchingProducts() {
  if (!sampleMatchProductList) return;
  const products = adminState.sampleMatchingProducts;
  sampleMatchProductList.innerHTML = products.length ? products.map((product) => `
    <div class="admin-compact-row sample-match-row" data-product-id="${escapeHtml(productKey(product))}">
      <strong>${escapeHtml(product.model)} · ${escapeHtml(product.brand)}</strong>
      <span>${sampleMatchStatusLabel(product.status)} · 置信度 ${Number(product.confidence || 0)}% · ${escapeHtml(product.reason || "")}</span>
      <div class="sample-match-bind-controls">
        <input class="sample-bind-folder-input" value="${escapeHtml(product.folderPath || "")}" placeholder="品牌/型号文件夹">
        <button class="sample-bind-product-folder" type="button">绑定</button>
      </div>
    </div>
  `).join("") : `<p class="empty-admin-text">当前筛选下没有商品</p>`;
}

function renderSampleAssets() {
  if (!sampleAssetSearchResults) return;
  const assets = adminState.sampleAssets;
  sampleAssetSearchResults.innerHTML = assets.length ? assets.map((asset) => `
    <div class="admin-compact-row">
      <strong>${escapeHtml(asset.modelFolder)} · ${escapeHtml(asset.brand)}</strong>
      <span>${escapeHtml(asset.folderPath)} · ${asset.imageCount} 张图 · ${escapeHtml(asset.modelKey)}</span>
      <button class="secondary-button sample-copy-folder" type="button" data-folder-path="${escapeHtml(asset.folderPath)}">复制路径</button>
    </div>
  `).join("") : `<p class="empty-admin-text">还没有图库搜索结果</p>`;
}

function renderSampleMatchingGroups() {
  if (!sampleMatchGroupList) return;
  const groups = adminState.sampleMatchingGroups;
  sampleMatchGroupList.innerHTML = groups.length ? groups.map((group, index) => `
    <div class="admin-compact-row sample-match-group-row" data-group-index="${index}">
      <strong>${escapeHtml(group.model)} · ${escapeHtml(group.brand)}</strong>
      <span>${sampleMatchStatusLabel(group.status)} · 影响 ${group.productCount} 台 · 置信度 ${Number(group.confidence || 0)}% · ${escapeHtml(group.folderPath)}</span>
      <button class="access-button sample-bind-group" type="button">确认这一组</button>
    </div>
  `).join("") : `<p class="empty-admin-text">当前没有可批量确认的候选组</p>`;
}

async function loadSampleMatchingSummary() {
  const summary = await requestJson("/api/admin/sample-matching/summary");
  renderSampleMatchingSummary(summary);
}

async function loadSampleMatchingProducts() {
  const status = document.getElementById("sampleMatchStatusFilter")?.value || "missing";
  const data = await requestJson(`/api/admin/sample-matching/products?status=${encodeURIComponent(status)}&limit=100`);
  adminState.sampleMatchingProducts = Array.isArray(data.products) ? data.products : [];
  renderSampleMatchingProducts();
}

async function loadSampleMatchingGroups() {
  const data = await requestJson("/api/admin/sample-matching/groups?limit=100");
  adminState.sampleMatchingGroups = Array.isArray(data.groups) ? data.groups : [];
  renderSampleMatchingGroups();
}

async function loadSampleMatchingCenter() {
  await Promise.all([loadSampleMatchingSummary(), loadSampleMatchingProducts(), loadSampleMatchingGroups()]);
}

async function searchSampleAssets() {
  const query = document.getElementById("sampleAssetSearchInput")?.value.trim() || "";
  const data = await requestJson(`/api/admin/sample-matching/assets?query=${encodeURIComponent(query)}&limit=40`);
  adminState.sampleAssets = Array.isArray(data.assets) ? data.assets : [];
  renderSampleAssets();
}

async function loadAdminApp() {
  loginPanel.hidden = true;
  adminApp.hidden = false;
  await Promise.all([loadSettings(), loadPartners(), loadProducts(), loadPurchaseStepsAdmin(), loadGalleryAlbums(), loadDiagnostics(), loadImportReports(), loadOperations(), loadSampleMatchingCenter()]);
  await loadSections();
}

let adminSearchTimer;
adminProductSearchInput?.addEventListener("input", (event) => {
  clearTimeout(adminSearchTimer);
  adminState.productController?.abort();
  ++adminState.productRequestId;
  adminState.productQuery = event.target.value.trim().toLowerCase();
  adminState.visibleProductCount = ADMIN_PRODUCT_PAGE_SIZE;
  adminSearchTimer = setTimeout(() => loadProducts(), 300);
});

for (const id of [
  "adminBrandFilterInput",
  "adminMinPriceInput",
  "adminMaxPriceInput",
  "adminVisibleFilterInput",
  "adminSoldFilterInput",
  "adminBodyImageFilterInput",
  "adminSampleImageFilterInput",
  "adminManualPriceFilterInput",
  "adminTagFilterInput",
]) {
  document.getElementById(id)?.addEventListener("change", () => {
    adminState.visibleProductCount = ADMIN_PRODUCT_PAGE_SIZE;
    adminState.selectedProductIds = new Set();
    loadProducts();
  });
}

document.getElementById("clearAdminFiltersButton")?.addEventListener("click", clearAdminFilters);

adminLoadMoreButton?.addEventListener("click", () => {
  loadProducts({ append: true });
});

async function uploadImage(productId, file) {
  const form = new FormData();
  form.append("imageType", "detail");
  form.append("file", file);
  const response = await fetch(`/api/admin/products/${encodeURIComponent(productId)}/images`, {
    method: "POST",
    body: form,
  });
  if (response.status === 401) {
    adminApp.hidden = true;
    loginPanel.hidden = false;
    loginError.textContent = "登录已过期，请重新登录；待上传文件仍保留";
    loginError.hidden = false;
  }
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function uploadGalleryImage(albumId, file, caption, isVisible) {
  const form = new FormData();
  form.append("caption", caption);
  form.append("isVisible", String(isVisible));
  form.append("file", file);
  const response = await fetch(`/api/admin/gallery/albums/${encodeURIComponent(albumId)}/images`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function reorderGalleryImages(albumRow, imageId, direction) {
  const ids = [...albumRow.querySelectorAll(".gallery-image-row")].map((node) => node.dataset.imageId);
  const index = ids.indexOf(imageId);
  const targetIndex = index + direction;
  if (index < 0 || targetIndex < 0 || targetIndex >= ids.length) return;
  [ids[index], ids[targetIndex]] = [ids[targetIndex], ids[index]];
  await requestJson(`/api/admin/gallery/albums/${encodeURIComponent(albumRow.dataset.albumId)}/images/reorder`, {
    method: "POST",
    body: JSON.stringify({ imageIds: ids }),
  });
  await loadGalleryAlbums();
}

async function loadImages(row) {
  const productId = row.dataset.productId;
  const data = await requestJson(`/api/admin/products/${encodeURIComponent(productId)}/images`);
  const images = Array.isArray(data.images) ? data.images : [];
  row.querySelector(".admin-image-list").innerHTML = images.map((image, index) => `
    <div class="admin-image-row" data-image-id="${escapeHtml(image.imageId)}">
      <span>${index + 1}. ${image.isCover ? "封面" : "详情图"}</span>
      <button class="admin-image-up" type="button">上移</button>
      <button class="admin-image-down" type="button">下移</button>
      <button class="admin-set-cover" type="button">设封面</button>
      <button class="admin-delete-image" type="button">删图</button>
    </div>
  `).join("");
}

async function reorderImages(row, imageId, direction) {
  const ids = [...row.querySelectorAll(".admin-image-row")].map((node) => node.dataset.imageId);
  const index = ids.indexOf(imageId);
  const targetIndex = index + direction;
  if (index < 0 || targetIndex < 0 || targetIndex >= ids.length) return;
  [ids[index], ids[targetIndex]] = [ids[targetIndex], ids[index]];
  await requestJson(`/api/admin/products/${encodeURIComponent(row.dataset.productId)}/images/reorder`, {
    method: "POST",
    body: JSON.stringify({ imageIds: ids }),
  });
  await loadImages(row);
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password: document.getElementById("adminPasswordInput").value }),
    });
    await loadAdminApp();
  } catch {
    loginError.textContent = "密码错误";
    loginError.hidden = false;
  }
});

document.getElementById("settingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.getElementById("customerPasswordAdminInput").value.trim();
  const payload = {
    statementText: document.getElementById("statementInput").value.trim(),
    shopIntroText: document.getElementById("shopIntroInput").value.trim(),
    watermarkText: document.getElementById("watermarkInput").value.trim() || "星星CCD",
    inventoryUpdatedAt: document.getElementById("inventoryUpdatedInput").value.trim(),
  };
  if (password) payload.customerPassword = password;
  await requestJson("/api/admin/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  document.getElementById("customerPasswordAdminInput").value = "";
  document.getElementById("settingsStatus").textContent = "已保存";
  await loadSettings();
});

document.getElementById("partnerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/partners", {
    method: "POST",
    body: JSON.stringify({
      name: document.getElementById("partnerNameInput").value.trim(),
      note: document.getElementById("partnerNoteInput").value.trim(),
      sortOrder: Number(document.getElementById("partnerSortInput").value || 0),
      active: document.getElementById("partnerActiveInput").checked,
    }),
  });
  event.target.reset();
  document.getElementById("partnerActiveInput").checked = true;
  await loadPartners();
});

document.getElementById("sectionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/sections", {
    method: "POST",
    body: JSON.stringify({
      title: document.getElementById("sectionTitleInput").value.trim(),
      subtitle: document.getElementById("sectionSubtitleInput").value.trim(),
      sortOrder: Number(document.getElementById("sectionSortInput").value || 0),
      active: document.getElementById("sectionActiveInput").checked,
    }),
  });
  event.target.reset();
  document.getElementById("sectionActiveInput").checked = true;
  await loadSections();
});

document.getElementById("galleryForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/gallery/albums", {
    method: "POST",
    body: JSON.stringify({
      title: document.getElementById("galleryTitleInput").value.trim(),
      description: document.getElementById("galleryDescriptionInput").value.trim(),
      sortOrder: Number(document.getElementById("gallerySortInput").value || 0),
      isVisible: document.getElementById("galleryVisibleInput").checked,
    }),
  });
  event.target.reset();
  document.getElementById("galleryVisibleInput").checked = true;
  await loadGalleryAlbums();
});

document.getElementById("purchaseStepForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/purchase-steps", {
    method: "POST",
    body: JSON.stringify({
      title: document.getElementById("purchaseStepTitleInput").value.trim(),
      description: document.getElementById("purchaseStepDescriptionInput").value.trim(),
      sortOrder: Number(document.getElementById("purchaseStepSortInput").value || 0),
      isVisible: document.getElementById("purchaseStepVisibleInput").checked,
    }),
  });
  event.target.reset();
  document.getElementById("purchaseStepVisibleInput").checked = true;
  await loadPurchaseStepsAdmin();
});

document.getElementById("backupDatabaseButton")?.addEventListener("click", () => {
  const status = document.getElementById("backupStatus");
  if (status) status.textContent = "请在 CCD 项目目录运行 backup_showcase_db.bat；它会同时备份数据库和所有已引用图片。";
});

document.getElementById("refreshDiagnosticsButton")?.addEventListener("click", async () => {
  await Promise.all([loadDiagnostics(), loadImportReports(), loadOperations()]);
});

document.getElementById("refreshSampleMatchingButton")?.addEventListener("click", async () => {
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在刷新";
  await loadSampleMatchingCenter();
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "已刷新";
});

document.getElementById("rebuildSampleMatchingButton")?.addEventListener("click", async () => {
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在重建";
  const result = await requestJson("/api/admin/sample-matching/rebuild", { method: "POST" });
  renderSampleMatchingSummary(result.summary || {});
  if (sampleMatchingStatus) {
    const imported = result.importResult || {};
    sampleMatchingStatus.textContent = `已重建：匹配 ${imported.matchedProductCount || 0} 台，写入 ${imported.insertedImageCount || 0} 张`;
  }
  await Promise.all([loadSampleMatchingProducts(), loadProducts(), loadDiagnostics()]);
});

document.getElementById("sampleMatchStatusFilter")?.addEventListener("change", loadSampleMatchingProducts);

document.getElementById("sampleAssetSearchButton")?.addEventListener("click", searchSampleAssets);

document.getElementById("sampleAssetSearchInput")?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  searchSampleAssets();
});

sampleAssetSearchResults?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-copy-folder")) return;
  const folderPath = event.target.dataset.folderPath || "";
  if (!folderPath) return;
  try {
    await navigator.clipboard?.writeText(folderPath);
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = `已复制：${folderPath}`;
  } catch {
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = folderPath;
  }
});

sampleMatchProductList?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-bind-product-folder")) return;
  const row = event.target.closest(".sample-match-row");
  const productId = row?.dataset.productId || "";
  const folderPath = row?.querySelector(".sample-bind-folder-input")?.value.trim() || "";
  if (!productId || !folderPath) return;
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在绑定";
  const result = await requestJson("/api/admin/sample-matching/bind", {
    method: "POST",
    body: JSON.stringify({ productId, folderPath }),
  });
  if (sampleMatchingStatus) {
    const imported = result.importResult || {};
    sampleMatchingStatus.textContent = `已绑定：${result.folderPath}，当前匹配 ${imported.matchedProductCount || 0} 台`;
  }
  await Promise.all([loadSampleMatchingCenter(), loadProducts(), loadDiagnostics()]);
});

sampleMatchGroupList?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-bind-group")) return;
  const row = event.target.closest(".sample-match-group-row");
  const group = adminState.sampleMatchingGroups[Number(row?.dataset.groupIndex || -1)];
  if (!group || !Array.isArray(group.productIds) || !group.productIds.length) return;
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在批量确认";
  const result = await requestJson("/api/admin/sample-matching/groups/bind", {
    method: "POST",
    body: JSON.stringify({
      productIds: group.productIds,
      folderPath: group.folderPath,
    }),
  });
  if (sampleMatchingStatus) {
    const imported = result.importResult || {};
    sampleMatchingStatus.textContent = `已确认 ${result.boundProductCount || 0} 台，当前匹配 ${imported.matchedProductCount || 0} 台`;
  }
  await Promise.all([loadSampleMatchingCenter(), loadProducts(), loadDiagnostics()]);
});

document.getElementById("operationList")?.addEventListener("click", async (event) => {
  const row = event.target.closest(".admin-compact-row");
  if (!row || !event.target.classList.contains("undo-operation")) return;
  if (event.target.disabled) return;
  const operationId = row.dataset.operationId;
  if (!adminState.undoKeys.has(operationId)) adminState.undoKeys.set(operationId, crypto.randomUUID());
  event.target.disabled = true;
  try {
    await requestJson(`/api/admin/operations/${encodeURIComponent(operationId)}/undo`, {
      method: "POST", body: JSON.stringify({ idempotencyKey: adminState.undoKeys.get(operationId) }),
    });
  } catch (error) { alert(`撤销未完成：${error.message}`); return; }
  finally { event.target.disabled = false; }
  await Promise.all([loadProducts(), loadOperations(), loadDiagnostics()]);
});

sectionList.addEventListener("click", async (event) => {
  const sectionRow = event.target.closest(".section-admin-row");
  if (!sectionRow) return;
  const sectionId = sectionRow.dataset.sectionId;

  if (event.target.classList.contains("section-save")) {
    await requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: sectionRow.querySelector(".section-title").value.trim(),
        subtitle: sectionRow.querySelector(".section-subtitle").value.trim(),
        sortOrder: Number(sectionRow.querySelector(".section-sort").value || 0),
        active: sectionRow.querySelector(".section-active").checked,
      }),
    });
    await loadSections();
  }

  if (event.target.classList.contains("section-delete")) {
    await requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}`, { method: "DELETE" });
    await loadSections();
  }

  if (event.target.classList.contains("section-product-search-button")) {
    await searchSectionProducts(sectionRow);
    return;
  }

  if (event.target.classList.contains("section-add-search-item")) {
    const resultRow = event.target.closest(".section-product-result");
    const productId = resultRow?.dataset.productId || "";
    if (!productId) return;
    await requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items`, {
      method: "POST",
      body: JSON.stringify({
        productId,
        recommendNote: sectionRow.querySelector(".section-new-note").value.trim(),
        sortOrder: Number(sectionRow.querySelector(".section-new-sort").value || 0),
      }),
    });
    adminState.sectionSearchResults[sectionId] = [];
    await loadSections();
    return;
  }

  const itemRow = event.target.closest(".section-item-row");
  if (!itemRow) return;
  const itemId = itemRow.dataset.itemId;

  if (event.target.classList.contains("section-item-save")) {
    await requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        recommendNote: itemRow.querySelector(".section-item-note").value.trim(),
        sortOrder: Number(itemRow.querySelector(".section-item-sort").value || 0),
      }),
    });
    await loadSections();
  }

  if (event.target.classList.contains("section-item-delete")) {
    await requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE" });
    await loadSections();
  }
});

galleryAlbumList?.addEventListener("click", async (event) => {
  const albumRow = event.target.closest(".gallery-admin-row");
  if (!albumRow) return;
  const albumId = albumRow.dataset.albumId;

  if (event.target.classList.contains("gallery-save")) {
    await requestJson(`/api/admin/gallery/albums/${encodeURIComponent(albumId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: albumRow.querySelector(".gallery-title").value.trim(),
        description: albumRow.querySelector(".gallery-description").value.trim(),
        sortOrder: Number(albumRow.querySelector(".gallery-sort").value || 0),
        isVisible: albumRow.querySelector(".gallery-visible").checked,
      }),
    });
    await loadGalleryAlbums();
  }

  if (event.target.classList.contains("gallery-delete")) {
    await requestJson(`/api/admin/gallery/albums/${encodeURIComponent(albumId)}`, { method: "DELETE" });
    await loadGalleryAlbums();
  }

  if (event.target.classList.contains("gallery-upload-image")) {
    const file = albumRow.querySelector(".gallery-image-file").files[0];
    if (!file) return;
    await uploadGalleryImage(
      albumId,
      file,
      albumRow.querySelector(".gallery-image-new-caption").value.trim(),
      albumRow.querySelector(".gallery-image-new-visible").checked,
    );
    await loadGalleryAlbums();
  }

  const imageRow = event.target.closest(".gallery-image-row");
  if (!imageRow) return;
  const imageId = imageRow.dataset.imageId;

  if (event.target.classList.contains("gallery-image-save")) {
    await requestJson(`/api/admin/gallery/images/${encodeURIComponent(imageId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        caption: imageRow.querySelector(".gallery-image-caption").value.trim(),
        sortOrder: Number(imageRow.querySelector(".gallery-image-sort").value || 0),
        isVisible: imageRow.querySelector(".gallery-image-visible").checked,
      }),
    });
    await loadGalleryAlbums();
  }

  if (event.target.classList.contains("gallery-image-up")) {
    await reorderGalleryImages(albumRow, imageId, -1);
  }

  if (event.target.classList.contains("gallery-image-down")) {
    await reorderGalleryImages(albumRow, imageId, 1);
  }

  if (event.target.classList.contains("gallery-image-delete")) {
    await requestJson(`/api/admin/gallery/images/${encodeURIComponent(imageId)}`, { method: "DELETE" });
    await loadGalleryAlbums();
  }
});

purchaseStepList?.addEventListener("click", async (event) => {
  const row = event.target.closest(".purchase-step-admin-row");
  if (!row) return;
  const stepId = row.dataset.stepId;

  if (event.target.classList.contains("purchase-step-save")) {
    await requestJson(`/api/admin/purchase-steps/${encodeURIComponent(stepId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: row.querySelector(".purchase-step-title").value.trim(),
        description: row.querySelector(".purchase-step-description").value.trim(),
        sortOrder: Number(row.querySelector(".purchase-step-sort").value || 0),
        isVisible: row.querySelector(".purchase-step-visible").checked,
      }),
    });
    await loadPurchaseStepsAdmin();
  }

  if (event.target.classList.contains("purchase-step-delete")) {
    await requestJson(`/api/admin/purchase-steps/${encodeURIComponent(stepId)}`, { method: "DELETE" });
    await loadPurchaseStepsAdmin();
  }
});

partnerList.addEventListener("click", async (event) => {
  const row = event.target.closest(".partner-admin-row");
  if (!row) return;
  const partnerId = row.dataset.partnerId;
  if (event.target.classList.contains("partner-save")) {
    await requestJson(`/api/admin/partners/${encodeURIComponent(partnerId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: row.querySelector(".partner-name").value.trim(),
        note: row.querySelector(".partner-note").value.trim(),
        sortOrder: Number(row.querySelector(".partner-sort").value || 0),
        active: row.querySelector(".partner-active").checked,
      }),
    });
    await loadPartners();
  }
  if (event.target.classList.contains("partner-delete")) {
    await requestJson(`/api/admin/partners/${encodeURIComponent(partnerId)}`, { method: "DELETE" });
    await loadPartners();
  }
});

document.getElementById("batchPriceForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (adminState.bulkBusy) return;
  adminState.lastBulkRequest = null;
  if (applyBulkButton) applyBulkButton.disabled = true;
  const previewRequestId = ++adminState.previewRequestId;
  const request = buildBulkRequest();
  try {
  const preview = await requestJson("/api/admin/products/bulk-preview", {
    method: "POST",
    body: JSON.stringify(request),
  });
  if (previewRequestId !== adminState.previewRequestId) return;
  adminState.lastBulkRequest = { previewId: preview.previewId, idempotencyKey: crypto.randomUUID() };
  renderBulkPreview(preview);
  if (applyBulkButton) applyBulkButton.disabled = preview.total === 0 || !preview.previewId;
  } catch (error) {
    if (previewRequestId === adminState.previewRequestId) bulkPreviewPanel.textContent = `预览失败：${error.message}`;
  }
});

function buildBulkRequest() {
  return {
    operation: document.getElementById("bulkOperationInput")?.value || "price",
    priceMode: document.getElementById("bulkPriceModeInput")?.value || "increment",
    amount: Number(document.getElementById("batchAmountInput")?.value || 0),
    productIds: [...adminState.selectedProductIds],
    filters: collectAdminFilters(),
  };
}

function renderBulkPreview(preview) {
  if (!bulkPreviewPanel) return;
  const items = Array.isArray(preview.items) ? preview.items : [];
  bulkPreviewPanel.innerHTML = `
    <div class="admin-compact-row">
      <strong>即将影响 ${preview.total || 0} 台商品</strong>
      <span>下方最多显示前 ${items.length} 台预览，确认后才会写入数据库。</span>
    </div>
    ${items.map((item) => `
      <div class="admin-compact-row">
        <strong>${escapeHtml(item.model)} · ${escapeHtml(item.brand)}</strong>
        <span>价格 ${item.oldPrice} -> ${item.newPrice}（${item.delta >= 0 ? "+" : ""}${item.delta}） · 状态 ${item.oldVisible ? "展示" : "隐藏"} -> ${item.newVisible ? "展示" : "隐藏"}</span>
      </div>
    `).join("")}
  `;
}

applyBulkButton?.addEventListener("click", async () => {
  if (!adminState.lastBulkRequest || adminState.bulkBusy) return;
  adminState.bulkBusy = true;
  applyBulkButton.disabled = true;
  try {
  const result = await requestJson("/api/admin/products/bulk-apply", {
    method: "POST",
    body: JSON.stringify(adminState.lastBulkRequest),
  });
  if (bulkPreviewPanel) {
    bulkPreviewPanel.innerHTML = `<div class="admin-compact-row"><strong>已执行</strong><span>影响 ${result.updatedCount} 台商品</span></div>`;
  }
  adminState.lastBulkRequest = null;
  applyBulkButton.disabled = true;
  adminState.selectedProductIds = new Set();
  await Promise.all([loadProducts(), loadSections(), loadDiagnostics(), loadOperations()]);
  } catch (error) {
    bulkPreviewPanel.textContent = `执行未确认：${error.message}。可重试同一预览，避免重复执行。`;
  } finally {
    adminState.bulkBusy = false;
    applyBulkButton.disabled = !adminState.lastBulkRequest;
  }
});

document.getElementById("createProductForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/products", {
    method: "POST",
    body: JSON.stringify({
      productId: document.getElementById("createProductIdInput").value.trim(),
      model: document.getElementById("createModelInput").value.trim(),
      brand: document.getElementById("createBrandInput").value.trim(),
      displayPrice: Number(document.getElementById("createPriceInput").value || 0),
      shortSellingPoint: document.getElementById("createSellingPointInput").value.trim(),
      recommendTags: inputToTags(document.getElementById("createTagsInput").value),
      displayCopy: document.getElementById("createCopyInput").value.trim(),
      sectionIds: collectCreateSectionIds(),
      sectionRecommendNote: document.getElementById("createSectionNoteInput").value.trim(),
      sectionSortOrder: Number(document.getElementById("createSectionSortInput").value || 0),
    }),
  });
  event.target.reset();
  renderCreateSectionPicker();
  await loadProducts();
  await loadSections();
});

adminProductList.addEventListener("click", async (event) => {
  const row = event.target.closest(".admin-product-row");
  if (!row) return;
  const productId = row.dataset.productId;
  if (event.target.classList.contains("admin-product-select")) {
    if (event.target.checked) {
      adminState.selectedProductIds.add(productId);
    } else {
      adminState.selectedProductIds.delete(productId);
    }
    return;
  }
  if (event.target.classList.contains("admin-discard-draft")) {
    adminState.drafts.delete(productId);
    await loadProducts();
    return;
  }
  if (event.target.classList.contains("admin-save-product")) {
    const draft = adminState.drafts.get(productId);
    if (!draft) return;
    event.target.disabled = true;
    try {
      const updated = await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, {
        method: "PATCH",
        body: JSON.stringify({ ...draft.changes, expectedVersion: draft.original.rowVersion }),
      });
      const latestDraft = adminState.drafts.get(productId);
      adminState.drafts.delete(productId);
      if (latestDraft && latestDraft !== draft) {
        const baseline = updated.product || updated;
        const changes = changedFields(baseline, readProductDraft(row));
        if (Object.keys(changes).length) adminState.drafts.set(productId, { original: baseline, changes });
      }
      const index = adminState.products.findIndex((product) => productKey(product) === productId);
      if (index >= 0) adminState.products[index] = { ...adminState.products[index], ...draft.changes, ...(updated.product || updated) };
      event.target.textContent = adminState.drafts.has(productId) ? "保存草稿" : "已保存";
      await loadSections();
    } catch (error) {
      event.target.textContent = error.status === 409 ? "版本冲突：草稿已保留" : "保存失败，草稿保留";
      alert(`保存未完成：${error.message}`);
    } finally { event.target.disabled = false; }
    return;
  }

  if (event.target.classList.contains("admin-toggle-visible")) {
    if (event.target.disabled) return;
    event.target.disabled = true;
    try {
      const index = adminState.products.findIndex((product) => productKey(product) === productId);
      const updated = await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, {
        method: "PATCH",
        body: JSON.stringify({ visible: row.dataset.visible !== "true", expectedVersion: adminState.products[index]?.rowVersion }),
      });
      adminState.products[index] = updated.product || updated;
      const draft = adminState.drafts.get(productId);
      if (draft) draft.original = { ...draft.original, rowVersion: adminState.products[index].rowVersion, visible: adminState.products[index].visible };
      row.dataset.visible = String(adminState.products[index].visible);
      event.target.textContent = adminState.products[index].visible ? "隐藏" : "显示";
      await loadSections();
    } catch (error) { alert(`更新未完成：${error.message}`); }
    finally { event.target.disabled = false; }
    return;
  }
  if (event.target.classList.contains("admin-reset-override")) {
    const field = event.target.dataset.resetField;
    const index = adminState.products.findIndex((product) => productKey(product) === productId);
    if (index < 0) return;
    event.target.disabled = true;
    try {
      const updated = await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, {
        method: "PATCH",
        body: JSON.stringify({
          expectedVersion: adminState.products[index].rowVersion,
          resetOverrides: [field],
        }),
      });
      adminState.products[index] = updated.product || updated;
      const draft = adminState.drafts.get(productId);
      if (draft) {
        const changeName = { price: "displayPrice", copy: "displayCopy", visibility: "visible" }[field];
        delete draft.changes[changeName];
        draft.original = adminState.products[index];
        if (!Object.keys(draft.changes).length) adminState.drafts.delete(productId);
      }
      renderAdminProducts();
    } catch (error) {
      alert(`恢复来源值失败：${error.message}`);
      event.target.disabled = false;
    }
    return;
  }
  if (event.target.classList.contains("admin-delete-product")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, { method: "DELETE" });
    await loadProducts();
    await loadSections();
  }
  if (event.target.classList.contains("admin-bind-sample-folder")) {
    const folderPath = row.querySelector(".admin-sample-folder-input").value.trim();
    if (!folderPath) return;
    await requestJson("/api/admin/sample-bindings", {
      method: "POST",
      body: JSON.stringify({
        productId,
        brand: row.querySelector(".admin-brand-input").value.trim(),
        modelKey: row.querySelector(".admin-model-input").value.trim(),
        folderPath,
      }),
    });
    await Promise.all([loadDiagnostics(), loadSampleMatchingCenter(), loadProducts()]);
  }
  if (event.target.classList.contains("admin-upload-image")) {
    const file = adminState.pendingImageFiles.get(productId) || row.querySelector(".admin-image-file").files[0];
    if (!file) return;
    await uploadImage(productId, file);
    adminState.pendingImageFiles.delete(productId);
    await loadImages(row);
  }
  if (event.target.classList.contains("admin-load-images")) {
    await loadImages(row);
  }
  const imageRow = event.target.closest(".admin-image-row");
  if (!imageRow) return;
  const imageId = imageRow.dataset.imageId;
  if (event.target.classList.contains("admin-image-up")) {
    await reorderImages(row, imageId, -1);
  }
  if (event.target.classList.contains("admin-image-down")) {
    await reorderImages(row, imageId, 1);
  }
  if (event.target.classList.contains("admin-set-cover")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}/images/${encodeURIComponent(imageId)}/cover`, { method: "POST" });
    await loadImages(row);
  }
  if (event.target.classList.contains("admin-delete-image")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}/images/${encodeURIComponent(imageId)}`, { method: "DELETE" });
    await loadImages(row);
  }
});
