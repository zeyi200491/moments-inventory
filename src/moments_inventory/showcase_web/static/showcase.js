const { productKey, imageUrl, changedFields, imageVariants } = ShowcaseUtils;
const state = {
  products: [],
  total: 0,
  hasMore: false,
  catalogRevision: "",
  loading: false,
  loadError: "",
  loadNotice: "",
  sections: [],
  gallery: [],
  purchaseSteps: [],
  query: "",
  brands: new Set(),
  priceMin: null,
  priceMax: null,
  tags: new Set(),
  sort: "latest",
  filters: {
    brands: [],
    tags: [],
    pricePresets: [],
  },
  currentDetailProduct: null,
  productRegistry: new Map(),
  copyButtonTimers: new WeakMap(),
  productRequestController: null,
  productRequestId: 0,
  restoreGeneration: 0,
  settings: {
    statementText: "",
    shopIntroText: "",
    watermarkText: "星星CCD",
    inventoryUpdatedAt: "",
    partners: [],
  },
};

const PRODUCT_PAGE_SIZE = 80;
const SEARCH_DEBOUNCE_MS = 300;
const LIST_STATE_KEY = "xingxing-showcase-list-state";
const quickFilterPanel = document.querySelector(".quick-filter-panel");
if (quickFilterPanel) quickFilterPanel.open = !window.matchMedia("(max-width: 600px)").matches;
let searchDebounceTimer = null;
let copyActionId = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function priceText(value) {
  return Number.isFinite(value) ? `${value} 元` : "询价";
}

function buildInquiryText(product) {
  const url = `${window.location.origin}/product?id=${encodeURIComponent(productKey(product))}`;
  return [
    "我想咨询这台 CCD",
    "",
    `型号：${product.model || ""}`,
    `品牌：${product.brand || ""}`,
    `价格：${product.displayPrice || 0} 元`,
    "",
    "完整文案：",
    product.displayCopy || product.rawCopy || "",
    "",
    "商品链接：",
    url,
  ].join("\n");
}
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return { copied: true, manualFallback: false };
    } catch {
      // 权限拒绝时继续尝试传统复制和可手动选择的文本框。
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "readonly");
  textarea.className = "copy-fallback-textarea";
  document.body.appendChild(textarea);
  let copied = false;
  try {
    textarea.select();
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  } finally {
    textarea.remove();
  }
  if (copied) return { copied: true, manualFallback: false };
  if (typeof window.prompt === "function") {
    window.prompt("自动复制失败，请手动复制以下完整咨询文案：", text);
    return { copied: false, manualFallback: true };
  }
  return { copied: false, manualFallback: false };
}

function renderTags(tags) {
  const normalized = Array.isArray(tags) ? tags.filter(Boolean).slice(0, 4) : [];
  return normalized.length
    ? `<div class="tag-row">${normalized.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`
    : "";
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(String(value ?? ""));
  }
  return String(value ?? "").replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

const FILTER_STICKER_SEQUENCE = [
  "filter-001.png",
  "filter-002.png",
  "filter-003.png",
  "filter-004.png",
  "filter-005.png",
  "filter-006.png",
  "filter-007.png",
  "filter-008.png",
  "filter-009.png",
  "filter-010.png",
  "filter-011.png",
  "filter-012.png",
  "filter-013.png",
  "filter-014.png",
  "filter-015.png",
  "filter-016.png",
  "filter-017.png",
  "filter-018.png",
  "filter-019.png",
  "filter-020.png",
  "filter-021.png",
  "filter-022.png",
  "filter-023.png",
  "filter-024.png",
  "filter-025.png",
];

function filterStickerUrlByIndex(index = 0) {
  const normalized = Number.isFinite(index) ? Math.max(0, index) : 0;
  const icon = FILTER_STICKER_SEQUENCE[normalized % FILTER_STICKER_SEQUENCE.length];
  return `/static/assets/theme/filter-stickers/${icon}`;
}

function filterButtonLabel(label, index = 0) {
  const stickerUrl = filterStickerUrlByIndex(index);
  return `<span class="filter-sticker" style="--sticker-image: url('${stickerUrl}')" aria-hidden="true"></span><span class="filter-label">${escapeHtml(label)}</span>`;
}

function setWatermark(text) {
  const target = document.getElementById("siteWatermark");
  if (!target) return;
  const watermarkText = text || "星星CCD";
  target.dataset.watermark = Array(8).fill(watermarkText).join("  ");
}

async function loadSettings() {
  const response = await fetch("/api/public/settings");
  if (!response.ok) return state.settings;
  state.settings = await response.json();
  setWatermark(state.settings.watermarkText);
  return state.settings;
}

function renderPartners(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const partners = Array.isArray(state.settings.partners) ? state.settings.partners : [];
  target.innerHTML = partners.length
    ? partners.map((partner) => `<span>${escapeHtml(partner.name)}${partner.note ? ` · ${escapeHtml(partner.note)}` : ""}</span>`).join("")
    : `<span>\u6682\u65e0\u516c\u5f00\u6388\u6743\u5408\u4f5c\u65b9</span>`;
}

function showAccessPanel(onUnlocked) {
  const panel = document.getElementById("accessPanel");
  const form = document.getElementById("customerAccessForm");
  const error = document.getElementById("customerAccessError");
  if (!panel || !form) return;
  document.getElementById("inventoryApp")?.setAttribute("hidden", "");
  document.getElementById("detailApp")?.setAttribute("hidden", "");
  const statement = document.getElementById("accessStatement");
  if (statement) statement.textContent = state.settings.statementText || "";
  renderPartners("authorizedPartners");
  panel.hidden = false;

  let submitting = false;
  const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    if (submitButton) submitButton.disabled = true;
    if (error) error.hidden = true;
    const password = document.getElementById("customerPasswordInput")?.value || "";
    try {
      let response;
      try {
        response = await fetch("/api/public/access", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password }),
        });
      } catch {
        if (error) {
          error.textContent = "网络连接失败，请检查网络后重试";
          error.hidden = false;
        }
        return;
      }

      if (!response.ok) {
        if (error) {
          error.textContent = response.status === 401 || response.status === 403
            ? "口令不正确，请找星星CCD获取本周口令"
            : response.status === 429
              ? "尝试次数过多，请稍后再试"
              : "服务暂时不可用，请稍后重试";
          error.hidden = false;
        }
        return;
      }
      panel.hidden = true;
      await onUnlocked();
    } finally {
      submitting = false;
      if (submitButton) submitButton.disabled = false;
    }
  };
}

async function ensureCustomerAccess(onUnlocked) {
  const response = await fetch("/api/public/access-status");
  if (!response.ok) return true;
  const status = await response.json();
  if (status.requiresPassword && !status.authorized) {
    showAccessPanel(onUnlocked);
    return false;
  }
  return true;
}

function renderBrands() {
  const brandTarget = document.getElementById("brandFilterButtons");
  if (!brandTarget) return;
  const brands = Array.isArray(state.filters.brands) ? state.filters.brands : [];
  brandTarget.innerHTML = brands.map((brand, index) => `
    <button class="quick-filter-button sticker-filter-button ${state.brands.has(brand) ? "active" : ""}" type="button" data-brand="${escapeHtml(brand)}">${filterButtonLabel(brand, index)}</button>
  `).join("");
  renderActiveFilters();
}

function reconcileSelectedBrands() {
  if (!Array.isArray(state.filters.brands)) return;
  const availableBrands = new Set(state.filters.brands.map(String));
  for (const brand of [...state.brands]) {
    if (!availableBrands.has(brand)) state.brands.delete(brand);
  }
}

function buildProductQuery(offset = 0) {
  const params = new URLSearchParams();
  params.set("limit", String(PRODUCT_PAGE_SIZE));
  params.set("offset", String(offset));
  if (offset > 0 && state.catalogRevision) params.set("expectedRevision", state.catalogRevision);
  if (state.query) params.set("query", state.query);
  if (state.brands.size) params.set("brands", [...state.brands].join(","));
  if (state.priceMin !== null) params.set("priceMin", String(state.priceMin));
  if (state.priceMax !== null) params.set("priceMax", String(state.priceMax));
  if (state.tags.size) params.set("tags", [...state.tags].join(","));
  if (state.sort) params.set("sort", state.sort);
  return params.toString();
}

function saveListState(productId = "") {
  const snapshot = {
    query: state.query,
    brands: [...state.brands],
    priceMin: state.priceMin,
    priceMax: state.priceMax,
    tags: [...state.tags],
    sort: state.sort,
    loadedCount: state.products.length,
    scrollY: window.scrollY,
    selectedProductId: productId,
  };
  try {
    sessionStorage.setItem(LIST_STATE_KEY, JSON.stringify(snapshot));
  } catch {
    // 浏览器禁用会话存储时不阻断商品详情跳转。
  }
}

function readListState() {
  try {
    const raw = sessionStorage.getItem(LIST_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function clearListState() {
  try {
    sessionStorage.removeItem(LIST_STATE_KEY);
  } catch {
    // Ignore storage failures; navigation and filtering should continue.
  }
}

function hasSavedListState() {
  try {
    return Boolean(sessionStorage.getItem(LIST_STATE_KEY));
  } catch {
    return false;
  }
}

function cancelListRestore() {
  state.restoreGeneration += 1;
}

function isCurrentOriginInventoryReferrer() {
  if (!document.referrer) return false;
  try {
    const referrerUrl = new URL(document.referrer);
    return referrerUrl.origin === window.location.origin && referrerUrl.pathname === "/";
  } catch {
    return false;
  }
}

async function loadProductPage({ reset = false, restoreToken = null } = {}) {
  if (!reset && state.loading) return;
  if (reset && restoreToken === null) {
    cancelListRestore();
  }
  if (reset && state.productRequestController) {
    state.productRequestController.abort();
  }
  const requestId = state.productRequestId + 1;
  const controller = new AbortController();
  state.productRequestId = requestId;
  state.productRequestController = controller;
  state.loading = true;
  state.loadError = "";
  if (reset && restoreToken !== "revision-refresh") state.loadNotice = "";
  if (reset) syncFilterUrl();
  if (reset) {
    state.productRegistry.clear();
    state.products = [];
    state.total = 0;
    state.hasMore = false;
    state.catalogRevision = "";
  }
  renderList({ replaceProducts: reset });
  const offset = reset ? 0 : state.products.length;
  try {
    const response = await fetch(`/api/public/products?${buildProductQuery(offset)}`, {
      signal: controller.signal,
    });
    if (requestId !== state.productRequestId) return;
    if (response.status === 401) {
      showAccessPanel(loadInventory);
      return;
    }
    if (response.status === 409 && !reset) {
      state.loadNotice = "库存刚刚更新，已为你刷新列表";
      return loadProductPage({ reset: true, restoreToken: "revision-refresh" });
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (requestId !== state.productRequestId) return;
    const products = Array.isArray(data.products) ? data.products : [];
    const known = new Set(state.products.map(productKey));
    const added = products.filter((product) => !known.has(productKey(product)));
    state.products = reset ? products : [...state.products, ...added];
    state.total = Number(data.total || 0);
    state.catalogRevision = String(data.catalogRevision || "");
    state.hasMore = Boolean(data.hasMore) && (reset ? products.length > 0 : added.length > 0);
    renderList({ replaceProducts: reset, appendProducts: reset ? [] : added });
    return true;
  } catch (error) {
    if (error.name !== "AbortError" && requestId === state.productRequestId) {
      state.loadError = "库存加载失败，请重试";
      renderList({ replaceProducts: false });
    }
    return false;
  } finally {
    if (requestId === state.productRequestId) {
      state.loading = false;
      if (state.productRequestController === controller) {
        state.productRequestController = null;
      }
      renderList({ replaceProducts: false });
    }
  }
}

async function loadFilters() {
  const response = await fetch("/api/public/filters");
  if (!response.ok) return;
  state.filters = await response.json();
  reconcileSelectedBrands();
  renderBrands();
  renderQuickFilters();
}

function renderQuickFilters() {
  const tagTarget = document.getElementById("tagFilterButtons");
  const priceTarget = document.getElementById("pricePresetButtons");
  const brandCount = Array.isArray(state.filters.brands) ? state.filters.brands.length : 0;
  const tags = Array.isArray(state.filters.tags) ? state.filters.tags : [];
  if (tagTarget) {
    tagTarget.innerHTML = tags.map((tag, index) => `
      <button class="quick-filter-button sticker-filter-button ${state.tags.has(tag) ? "active" : ""}" type="button" data-tag="${escapeHtml(tag)}">${filterButtonLabel(tag, brandCount + index)}</button>
    `).join("");
  }
  if (priceTarget) {
    const presets = Array.isArray(state.filters.pricePresets) ? state.filters.pricePresets : [];
    priceTarget.innerHTML = presets.map((preset, index) => {
      const priceMin = Number(preset.priceMin);
      const priceMax = Number(preset.priceMax);
      const active = state.priceMin === priceMin && state.priceMax === priceMax;
      return `
        <button class="quick-filter-button sticker-filter-button ${active ? "active" : ""}" type="button" data-price-min="${priceMin}" data-price-max="${priceMax}">${filterButtonLabel(preset.label, brandCount + tags.length + index)}</button>
      `;
    }).join("");
  }
  renderActiveFilters();
}

function sortLabel(value) {
  if (value === "price_asc") return "价格低到高";
  if (value === "price_desc") return "价格高到低";
  return "最新";
}

function priceRangeLabel() {
  if (state.priceMin === null && state.priceMax === null) return "";
  if (state.priceMin === 0 && state.priceMax !== null) return `${state.priceMax}以内`;
  if (state.priceMin !== null && state.priceMax !== null) return `${state.priceMin}-${state.priceMax}`;
  if (state.priceMin !== null) return `${state.priceMin}以上`;
  return "";
}

function renderActiveFilters() {
  const target = document.getElementById("activeFilterSummary");
  if (!target) return;
  const parts = [];
  if (state.query) parts.push(`搜索：${state.query}`);
  if (state.brands.size) parts.push([...state.brands].join(" / "));
  const priceLabel = priceRangeLabel();
  if (priceLabel) parts.push(priceLabel);
  if (state.tags.size) parts.push([...state.tags].join(" / "));
  if (state.sort && state.sort !== "latest") parts.push(sortLabel(state.sort));
  target.hidden = parts.length === 0;
  target.textContent = parts.length ? `已选：${parts.join(" · ")}` : "";
}

function clearFilters() {
  state.query = "";
  state.brands = new Set();
  state.priceMin = null;
  state.priceMax = null;
  state.tags = new Set();
  state.sort = "latest";
  const searchInput = document.getElementById("searchInput");
  const priceFilter = document.getElementById("priceFilter");
  const sortFilter = document.getElementById("sortFilter");
  if (searchInput) searchInput.value = "";
  if (priceFilter) priceFilter.value = "";
  if (sortFilter) sortFilter.value = "latest";
  renderBrands();
  renderQuickFilters();
}

function renderProductCard(product) {
  state.productRegistry.set(productKey(product), product);
  const detailUrl = `/product?id=${encodeURIComponent(productKey(product))}`;
  const copyButtonLabel = "\u590d\u5236\u54a8\u8be2\u6587\u6848\uff08\u70b9\u4e00\u4e0b\u590d\u5236\u8fd9\u53f0\u5b8c\u6574\u6587\u6848\uff0c\u56de\u5fae\u4fe1\u53d1\u7ed9\u6211\uff09";
  const copyButtonShortLabel = "\u590d\u5236\u54a8\u8be2\u6587\u6848";
  const image = (product.coverImageUrl || product.coverImagePath)
    ? `<img loading="lazy" src="${escapeHtml(imageUrl(product.coverImageUrl || product.coverImagePath))}" srcset="${escapeHtml(imageVariants(product.coverImageUrl || product.coverImagePath))}" sizes="(max-width: 600px) 50vw, 320px" alt="">`
    : `<div class="product-placeholder" aria-label="\u6682\u65e0\u5546\u54c1\u56fe"></div>`;
  const sellingPoint = product.shortSellingPoint || product.recommendNote || "";
  return `<article class="product-card">
    <a class="product-detail-link" data-product-link="true" href="${detailUrl}" aria-label="${escapeHtml(product.model)} \u67e5\u770b\u8be6\u60c5">
      <div class="product-media">
        ${image}
        ${product.coverImageType === "sample" ? `<span class="sample-cover-label">同型号出片参考</span>` : ""}
        ${renderTags(product.recommendTags)}
      </div>
      <div class="product-content">
        <div class="product-title-row">
          <h2>${escapeHtml(product.model)}</h2>
          <div class="price">${priceText(product.displayPrice)}</div>
        </div>
        <div class="meta-row">${escapeHtml(product.brand || "\u672a\u8bc6\u522b\u54c1\u724c")}</div>
        ${sellingPoint ? `<p class="selling-point">${escapeHtml(sellingPoint)}</p>` : ""}
        <p class="copy">${escapeHtml(product.displayCopy || "")}</p>
      </div>
    </a>
    <div class="product-card-actions">
      <button class="copy-inquiry-button" type="button" data-product-id="${escapeHtml(productKey(product))}" data-default-label="${escapeHtml(copyButtonLabel)}" data-short-label="${escapeHtml(copyButtonShortLabel)}">${copyButtonLabel}</button>
    </div>
  </article>`;
}

function installImageFallbacks() {
  document.addEventListener("error", (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    if (image.hasAttribute("srcset")) {
      image.removeAttribute("srcset");
      image.src = image.getAttribute("src");
      return;
    }
    const media = image.closest(".product-media");
    if (!media || media.querySelector(".product-placeholder")) return;
    const placeholder = document.createElement("div");
    placeholder.className = "product-placeholder";
    placeholder.setAttribute("aria-label", "暂无商品图");
    image.replaceWith(placeholder);
  }, true);
}

async function restoreListStateIfAvailable() {
  const saved = readFilterUrl() || readListState();
  if (!saved) return false;
  const restoreToken = state.restoreGeneration + 1;
  state.restoreGeneration = restoreToken;

  state.query = String(saved.query || "");
  state.brands = new Set(
    Array.isArray(saved.brands)
      ? saved.brands.filter(Boolean).map(String)
      : (saved.brand ? [String(saved.brand)] : [])
  );
  state.priceMin = saved.priceMin === null || saved.priceMin === undefined ? null : Number(saved.priceMin);
  state.priceMax = saved.priceMax === null || saved.priceMax === undefined ? null : Number(saved.priceMax);
  if (!Number.isFinite(state.priceMin)) state.priceMin = null;
  if (!Number.isFinite(state.priceMax)) state.priceMax = null;
  state.tags = new Set(Array.isArray(saved.tags) ? saved.tags.filter(Boolean).map(String) : []);
  state.sort = ["latest", "price_asc", "price_desc"].includes(saved.sort) ? saved.sort : "latest";

  const searchInput = document.getElementById("searchInput");
  const priceFilter = document.getElementById("priceFilter");
  const sortFilter = document.getElementById("sortFilter");
  if (searchInput) searchInput.value = state.query;
  renderBrands();
  if (priceFilter) {
    priceFilter.value = state.priceMin !== null && state.priceMax !== null
      ? `${state.priceMin}-${state.priceMax}`
      : "";
  }
  if (sortFilter) sortFilter.value = state.sort;
  renderQuickFilters();

  const savedLoadedCount = Number(saved.loadedCount || PRODUCT_PAGE_SIZE);
  const targetCount = Math.max(PRODUCT_PAGE_SIZE, Number.isFinite(savedLoadedCount) ? savedLoadedCount : PRODUCT_PAGE_SIZE);
  let restoredPages = 0;
  while (state.products.length < targetCount && restoredPages < 5) {
    const beforeCount = state.products.length;
    restoredPages += 1;
    if (restoreToken !== state.restoreGeneration) return true;
    const loaded = await loadProductPage({ reset: state.products.length === 0, restoreToken });
    if (!loaded || state.products.length <= beforeCount) break;
    if (restoreToken !== state.restoreGeneration) return true;
    if (!state.hasMore) break;
  }
  const fullyRestored = state.products.length >= targetCount || !state.hasMore;
  if (fullyRestored) {
    clearListState();
  } else {
    state.loadError = `已恢复前 ${state.products.length} 台，点击“显示更多”可继续恢复浏览位置`;
    renderList();
  }
  window.setTimeout(() => {
    if (restoreToken !== state.restoreGeneration) return;
    const scrollY = Number(saved.scrollY || 0);
    window.scrollTo(0, Number.isFinite(scrollY) ? scrollY : 0);
  }, 50);
  return true;
}

function renderFeaturedSections() {
  const target = document.getElementById("featuredSections");
  if (!target) return;
  const sections = Array.isArray(state.sections) ? state.sections : [];
  target.innerHTML = sections.length
    ? sections.map((section, index) => {
        const isLeadSection = index === 0;
        const products = Array.isArray(section.products) ? section.products.slice(0, isLeadSection ? 6 : 8) : [];
        return `<section class="featured-section ${isLeadSection ? "featured-section-lead" : "featured-section-compact"}">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${isLeadSection ? "Today Pick" : "Selection"}</p>
              <h2>${escapeHtml(section.title)}</h2>
              ${section.subtitle ? `<p>${escapeHtml(section.subtitle)}</p>` : ""}
            </div>
            <span>${products.length} \u53f0</span>
          </div>
          <div class="${isLeadSection ? "featured-lead-grid" : "featured-scroll-row"}">
            ${products.map(renderProductCard).join("")}
          </div>
        </section>`;
      }).join("")
    : "";
}

async function loadStoreGallery() {
  const response = await fetch("/api/public/gallery");
  if (!response.ok) {
    state.gallery = [];
    return;
  }
  const data = await response.json();
  state.gallery = Array.isArray(data.albums) ? data.albums : [];
}

async function loadPurchaseSteps() {
  const response = await fetch("/api/public/purchase-steps");
  if (!response.ok) {
    state.purchaseSteps = [];
    return;
  }
  const data = await response.json();
  state.purchaseSteps = Array.isArray(data.steps) ? data.steps : [];
}

function renderPurchaseSteps() {
  const target = document.getElementById("purchaseSteps");
  if (!target) return;
  const steps = Array.isArray(state.purchaseSteps) ? state.purchaseSteps : [];
  if (!steps.length) {
    target.innerHTML = "";
    target.hidden = true;
    return;
  }
  target.hidden = false;
  target.innerHTML = `<div class="purchase-steps-heading">
      <div>
        <p class="eyebrow">Before Buying</p>
        <h2>买前流程</h2>
      </div>
      <span>${steps.length} 步</span>
    </div>
    <div class="purchase-step-track">
      ${steps.map((step, index) => `<article class="purchase-step-card">
        <span class="purchase-step-index">${index + 1}</span>
        <div>
          <h3>${escapeHtml(step.title)}</h3>
          ${step.description ? `<p>${escapeHtml(step.description)}</p>` : ""}
        </div>
      </article>`).join("")}
    </div>`;
}

function renderStoreGallery() {
  const target = document.getElementById("storeGallery");
  if (!target) return;
  const albums = Array.isArray(state.gallery)
    ? state.gallery.filter((album) => Array.isArray(album.images) && album.images.length)
    : [];
  if (!albums.length) {
    target.innerHTML = "";
    target.hidden = true;
    return;
  }
  target.hidden = false;
  target.innerHTML = `<div class="store-gallery-heading">
      <div>
        <p class="eyebrow">Shop Window</p>
        <h2>星星CCD小铺实景展示</h2>
      </div>
      <span>${albums.length} 个相册</span>
    </div>
    <div class="store-gallery-list">
      ${albums.map(renderStoreGalleryAlbum).join("")}
    </div>`;
  bindStoreGalleryScroll();
}

function renderStoreGalleryAlbum(album) {
  const images = Array.isArray(album.images) ? album.images : [];
  const imagePaths = images.map((image) => image.imagePath).join("|");
  return `<article class="store-gallery-album">
    <div class="store-gallery-album-head">
      <div>
        <h3>${escapeHtml(album.title)}</h3>
        ${album.description ? `<p>${escapeHtml(album.description)}</p>` : ""}
      </div>
      <span>${images.length} 张</span>
    </div>
    <div class="store-gallery-thumbnails" data-gallery-id="${escapeHtml(album.albumId)}">
      ${images.map((image, index) => `<button class="store-gallery-thumb image-preview-trigger" type="button" data-gallery="${escapeHtml(album.title)}" data-index="${index}" data-images="${escapeHtml(imagePaths)}">
        <img loading="lazy" src="${escapeHtml(imageUrl(image.imageUrl || image.imagePath))}" srcset="${escapeHtml(imageVariants(image.imageUrl || image.imagePath))}" sizes="(max-width: 600px) 50vw, 480px" alt="${escapeHtml(image.caption || album.title)}">
        ${image.caption ? `<span>${escapeHtml(image.caption)}</span>` : ""}
      </button>`).join("")}
    </div>
  </article>`;
}

function bindStoreGalleryScroll() {
  document.querySelectorAll("[data-gallery-track]").forEach((track) => {
    track.addEventListener("scroll", () => {
      const albumId = track.dataset.galleryTrack;
      const slideWidth = Math.max(1, track.clientWidth);
      const activeIndex = Math.round(track.scrollLeft / slideWidth);
      setStoreGalleryActiveDot(albumId, activeIndex);
    }, { passive: true });
  });
}

function setStoreGalleryActiveDot(albumId, activeIndex) {
  const dots = document.querySelectorAll(`[data-gallery-dot="${cssEscape(albumId)}"]`);
  dots.forEach((dot, index) => {
    dot.classList.toggle("active", index === activeIndex);
  });
}

function moveStoreGallery(albumId, direction) {
  const track = document.querySelector(`[data-gallery-track="${cssEscape(albumId)}"]`);
  if (!track) return;
  const slideWidth = Math.max(1, track.clientWidth);
  const currentIndex = Math.round(track.scrollLeft / slideWidth);
  const maxIndex = Math.max(0, track.children.length - 1);
  const nextIndex = Math.max(0, Math.min(maxIndex, currentIndex + direction));
  track.scrollTo({ left: nextIndex * slideWidth, behavior: "smooth" });
  setStoreGalleryActiveDot(albumId, nextIndex);
}

function jumpStoreGallery(albumId, index) {
  const track = document.querySelector(`[data-gallery-track="${cssEscape(albumId)}"]`);
  if (!track) return;
  const slideWidth = Math.max(1, track.clientWidth);
  track.scrollTo({ left: index * slideWidth, behavior: "smooth" });
  setStoreGalleryActiveDot(albumId, index);
}

function renderStatement() {
  const statementPanel = document.getElementById("statementPanel");
  const updatedAt = document.getElementById("inventoryUpdatedAt");
  if (updatedAt) {
    updatedAt.textContent = state.settings.inventoryUpdatedAt
      ? `\u5e93\u5b58\u66f4\u65b0\uff1a${state.settings.inventoryUpdatedAt}`
      : "";
  }
  if (!statementPanel) return;
  const intro = state.settings.shopIntroText || "";
  statementPanel.innerHTML = `<p>${escapeHtml(state.settings.statementText || "")}</p>
    ${intro ? `<section class="shop-intro-panel"><h2>店铺简介</h2><p>${escapeHtml(intro)}</p></section>` : ""}
    <div class="partner-list" id="statementPartners"></div>`;
  renderPartners("statementPartners");
}

function renderList({ replaceProducts = true, appendProducts = [] } = {}) {
  const productGrid = document.getElementById("productGrid");
  const emptyState = document.getElementById("emptyState");
  const resultCount = document.getElementById("resultCount");
  const loadMoreButton = document.getElementById("loadMoreButton");
  if (!productGrid || !emptyState || !resultCount) return;
  const products = state.products;
  if (replaceProducts) {
    productGrid.innerHTML = products.map(renderProductCard).join("");
  } else if (appendProducts.length) {
    productGrid.insertAdjacentHTML("beforeend", appendProducts.map(renderProductCard).join(""));
  }
  resultCount.textContent = products.length === state.total
    ? `${state.total} 台`
    : `${products.length} / ${state.total} 台`;
  emptyState.hidden = state.loading || products.length !== 0 || Boolean(state.loadError);
  const errorPanel = document.getElementById("listError");
  const errorMessage = document.getElementById("listErrorMessage");
  const message = state.loadError || state.loadNotice;
  if (errorMessage) errorMessage.textContent = message;
  if (errorPanel) errorPanel.hidden = !message;
  if (loadMoreButton) {
    loadMoreButton.hidden = !state.hasMore && !state.loading;
    loadMoreButton.textContent = state.loading ? "\u52a0\u8f7d\u4e2d" : "\u663e\u793a\u66f4\u591a";
    loadMoreButton.disabled = state.loading;
  }
}

function syncFilterUrl() {
  if (!document.getElementById("productGrid")) return;
  const params = new URLSearchParams(buildProductQuery());
  params.delete("offset"); params.delete("limit");
  if (params.get("sort") === "latest") params.delete("sort");
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function readFilterUrl() {
  const params = new URLSearchParams(window.location.search);
  if (!["query", "brands", "tags", "priceMin", "priceMax", "sort"].some((key) => params.has(key))) return null;
  const saved = readListState();
  return { ...saved, query: params.get("query") || "", brands: (params.get("brands") || "").split(",").filter(Boolean),
    tags: (params.get("tags") || "").split(",").filter(Boolean), priceMin: params.get("priceMin"),
    priceMax: params.get("priceMax"), sort: params.get("sort") || "latest" };
}

function bindFilters() {
  document.getElementById("retryProductsButton")?.addEventListener("click", () => loadProductPage({ reset: state.products.length === 0 }));
  document.getElementById("searchInput")?.addEventListener("input", (event) => {
    cancelListRestore();
    state.query = event.target.value.trim();
    renderActiveFilters();
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(() => {
      loadProductPage({ reset: true });
    }, SEARCH_DEBOUNCE_MS);
  });
  document.getElementById("priceFilter")?.addEventListener("change", (event) => {
    cancelListRestore();
    const [min, max] = event.target.value
      ? event.target.value.split("-").map((part) => Number.parseInt(part, 10))
      : [null, null];
    state.priceMin = Number.isFinite(min) ? min : null;
    state.priceMax = Number.isFinite(max) ? max : null;
    renderQuickFilters();
    loadProductPage({ reset: true });
  });
  document.getElementById("sortFilter")?.addEventListener("change", (event) => {
    cancelListRestore();
    state.sort = event.target.value || "latest";
    renderActiveFilters();
    loadProductPage({ reset: true });
  });
  document.getElementById("clearFiltersButton")?.addEventListener("click", () => {
    cancelListRestore();
    clearFilters();
    loadProductPage({ reset: true });
  });
  document.getElementById("loadMoreButton")?.addEventListener("click", () => {
    loadProductPage({ reset: false });
  });
}

async function loadInventory() {
  document.getElementById("inventoryApp").hidden = false;
  renderStatement();
  const optional = Promise.allSettled([
    loadFilters(), loadStoreGallery(), loadPurchaseSteps(),
    fetch("/api/public/sections").then(async (response) => {
      if (response.ok) state.sections = (await response.json()).sections || [];
    }),
  ]).then(() => { renderPurchaseSteps(); renderStoreGallery(); renderFeaturedSections(); renderBrands(); });
  const restored = await restoreListStateIfAvailable();
  if (!restored) await loadProductPage({ reset: true });
  await optional;
}

async function initListPage() {
  const productGrid = document.getElementById("productGrid");
  if (!productGrid) return;
  await loadSettings();
  bindFilters();
  if (!await ensureCustomerAccess(loadInventory)) return;
  await loadInventory();
}

function renderDetail(product) {
  const target = document.getElementById("productDetail");
  if (!target) return;
  state.currentDetailProduct = product;
  state.productRegistry.set(productKey(product), product);
  const images = Array.isArray(product.images) ? product.images : [];
  const bodyImages = images.filter((image) => image.imageType !== "sample");
  const sampleImages = images.filter((image) => image.imageType === "sample");
  const copyButtonLabel = "复制咨询文案（点一下复制这台完整文案，回微信发给我）";
  const copyButtonShortLabel = "复制咨询文案";
  const imageGroupHtml = (title, note, group) => group.length
    ? `<section class="detail-image-section">
        <div class="section-heading compact-heading">
          <div>
            <h2>${escapeHtml(title)}</h2>
            ${note ? `<p>${escapeHtml(note)}</p>` : ""}
          </div>
          <span>${group.length} 张</span>
        </div>
        <div class="detail-images">${group.map((image, index) => `<button class="image-preview-trigger" type="button" aria-label="查看${escapeHtml(title)}图片，第${index + 1}张" data-gallery="${escapeHtml(title)}" data-index="${index}" data-images="${escapeHtml(group.map((item) => item.imagePath).join("|"))}"><img loading="lazy" src="${escapeHtml(imageUrl(image.imageUrl || image.imagePath))}" srcset="${escapeHtml(imageVariants(image.imageUrl || image.imagePath))}" sizes="(max-width: 600px) 50vw, 480px" alt=""></button>`).join("")}</div>
      </section>`
    : `<section class="empty-state">${escapeHtml(title)}暂未整理</section>`;
  target.innerHTML = `<article>
    <section class="detail-hero">
      <p class="eyebrow">${escapeHtml(product.brand || "CCD")}</p>
      <h1>${escapeHtml(product.model)}</h1>
      <p class="price">${priceText(product.displayPrice)}</p>
      ${renderTags(product.recommendTags)}
      ${product.shortSellingPoint ? `<p class="selling-point detail-selling-point">${escapeHtml(product.shortSellingPoint)}</p>` : ""}
      <button class="copy-inquiry-button detail-copy-button" type="button" data-product-id="${escapeHtml(productKey(product))}" data-default-label="${escapeHtml(copyButtonLabel)}" data-short-label="${escapeHtml(copyButtonShortLabel)}">${copyButtonLabel}</button>
    </section>
    ${imageGroupHtml("机身实拍图", "该台 CCD 的本体图片", bodyImages)}
    ${imageGroupHtml("出片参考图", "同型号出片参考，实际效果受光线和设置影响", sampleImages)}
    <section class="detail-copy-section">
      <h2>商品文案</h2>
      <p class="copy detail-copy">${escapeHtml(product.displayCopy || product.rawCopy || "")}</p>
    </section>
  </article>`;
}
function openImagePreview(images, index) {
  const previousFocus = document.activeElement;
  let currentIndex = Math.max(0, Math.min(index, images.length - 1));
  const modal = document.createElement("dialog");
  modal.className = "image-preview-modal";
  modal.setAttribute("aria-label", "图片预览");
  const close = () => { modal.close(); modal.remove(); previousFocus?.focus(); };
  modal.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  const render = () => {
    modal.innerHTML = `<div class="image-preview-backdrop"></div>
      <div class="image-preview-frame">
        <button class="preview-close" type="button" aria-label="关闭">×</button>
        <button class="preview-prev" type="button" aria-label="\u4e0a\u4e00\u5f20">\u2039</button>
        <img src="${escapeHtml(imageUrl(images[currentIndex]))}" alt="">
        <button class="preview-next" type="button" aria-label="\u4e0b\u4e00\u5f20">\u203a</button>
        <div class="preview-count">${currentIndex + 1} / ${images.length}</div>
      </div>`;
  };
  render();
  modal.addEventListener("click", (event) => {
    if (event.target.classList.contains("preview-close") || event.target.classList.contains("image-preview-backdrop")) {
      close();
    }
    if (event.target.classList.contains("preview-prev")) {
      currentIndex = (currentIndex - 1 + images.length) % images.length;
      render();
      modal.querySelector(".preview-prev").focus();
    }
    if (event.target.classList.contains("preview-next")) {
      currentIndex = (currentIndex + 1) % images.length;
      render();
      modal.querySelector(".preview-next").focus();
    }
  });
  document.body.appendChild(modal);
  modal.showModal();
  modal.querySelector(".preview-close").focus();
  modal.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      currentIndex = (currentIndex + (event.key === "ArrowLeft" ? -1 : 1) + images.length) % images.length;
      render();
      modal.querySelector(".preview-close").focus();
    }
  });
}

document.addEventListener("click", async (event) => {
  const copyButton = event.target.closest(".copy-inquiry-button");
  if (copyButton) {
    event.preventDefault();
    event.stopPropagation();
    const originalText = copyButton.dataset.defaultLabel || copyButton.textContent;
    const originalShortText = copyButton.dataset.shortLabel || originalText;
    const productId = copyButton.dataset.productId;
    const product = state.productRegistry.get(productId)
      || state.products.find((item) => item.productId === productId)
      || (state.currentDetailProduct && state.currentDetailProduct.productId === productId ? state.currentDetailProduct : null);
    if (!product) return;
    const copyToken = String(++copyActionId);
    copyButton.dataset.copyToken = copyToken;
    const activeTimer = state.copyButtonTimers.get(copyButton);
    if (activeTimer) {
      window.clearTimeout(activeTimer);
    }
    let copyResult = { copied: false, manualFallback: false };
    try {
      copyResult = await copyText(buildInquiryText(product));
    } catch { copyResult = { copied: false, manualFallback: false }; }
    if (copyButton.dataset.copyToken !== copyToken) return;
    const statusText = copyResult.copied
      ? "已复制"
      : copyResult.manualFallback ? "已提供手动复制文案" : "复制失败，请检查浏览器权限";
    copyButton.textContent = statusText;
    copyButton.dataset.shortLabel = statusText;
    const restoreTimer = window.setTimeout(() => {
      if (copyButton.dataset.copyToken !== copyToken) return;
      copyButton.textContent = originalText;
      copyButton.dataset.shortLabel = originalShortText;
      state.copyButtonTimers.delete(copyButton);
    }, 1600);
    state.copyButtonTimers.set(copyButton, restoreTimer);
    return;
  }
  const productLink = event.target.closest("[data-product-link], .product-detail-link");
  if (productLink && !event.target.closest(".copy-inquiry-button")) {
    const productId = new URL(productLink.href, window.location.href).searchParams.get("id") || "";
    saveListState(productId);
    return;
  }
  const brandButton = event.target.closest("[data-brand]");
  if (brandButton) {
    cancelListRestore();
    const brand = brandButton.dataset.brand;
    if (state.brands.has(brand)) {
      state.brands.delete(brand);
    } else {
      state.brands.add(brand);
    }
    renderBrands();
    loadProductPage({ reset: true });
    return;
  }
  const tagButton = event.target.closest("[data-tag]");
  if (tagButton) {
    cancelListRestore();
    const tag = tagButton.dataset.tag;
    if (state.tags.has(tag)) {
      state.tags.delete(tag);
    } else {
      state.tags.add(tag);
    }
    renderQuickFilters();
    loadProductPage({ reset: true });
    return;
  }
  const priceButton = event.target.closest("[data-price-min]");
  if (priceButton) {
    cancelListRestore();
    state.priceMin = Number(priceButton.dataset.priceMin);
    state.priceMax = Number(priceButton.dataset.priceMax);
    const priceFilter = document.getElementById("priceFilter");
    if (priceFilter) priceFilter.value = "";
    renderQuickFilters();
    loadProductPage({ reset: true });
    return;
  }
  const galleryNav = event.target.closest("[data-gallery-action]");
  if (galleryNav) {
    const direction = galleryNav.dataset.galleryAction === "prev" ? -1 : 1;
    moveStoreGallery(galleryNav.dataset.galleryId, direction);
    return;
  }
  const galleryDot = event.target.closest("[data-gallery-dot]");
  if (galleryDot) {
    const index = Number.parseInt(galleryDot.dataset.index || "0", 10);
    jumpStoreGallery(galleryDot.dataset.galleryDot, Number.isFinite(index) ? index : 0);
    return;
  }
  const trigger = event.target.closest(".image-preview-trigger");
  if (!trigger) return;
  const images = trigger.dataset.images.split("|").filter(Boolean);
  const index = Number.parseInt(trigger.dataset.index || "0", 10);
  if (images.length) openImagePreview(images, index);
});

document.querySelector("[data-back-to-list]")?.addEventListener("click", (event) => {
  if (window.history.length > 1 && (hasSavedListState() || isCurrentOriginInventoryReferrer())) {
    event.preventDefault();
    window.history.back();
  }
});

async function loadDetail(productId) {
  try {
  const target = document.getElementById("productDetail");
  const response = await fetch(`/api/public/product-lookup?id=${encodeURIComponent(productId)}`);
  if (response.status === 401) {
    showAccessPanel(() => loadDetail(productId));
    return;
  }
  document.getElementById("detailApp").hidden = false;
  if (response.status === 404) {
    target.innerHTML = `<section class="empty-state">\u5546\u54c1\u4e0d\u5b58\u5728\u6216\u5df2\u4e0b\u67b6</section>`;
    return;
  }
  if (!response.ok) {
    target.innerHTML = `<section class="empty-state">服务暂时不可用，请稍后重试。<button id="retryDetailButton" class="secondary-button" type="button">重新加载</button></section>`;
    document.getElementById("retryDetailButton")?.addEventListener("click", () => loadDetail(productId));
    return;
  }
  renderDetail(await response.json());
  } catch {
    document.getElementById("detailApp").hidden = false;
    document.getElementById("productDetail").innerHTML = `<section class="empty-state">详情加载失败，请检查网络后刷新重试</section>`;
  }
}

async function initDetailPage() {
  const target = document.getElementById("productDetail");
  if (!target) return;
  await loadSettings();
  const productId = new URLSearchParams(window.location.search).get("id");
  if (!productId) {
    document.getElementById("detailApp").hidden = false;
    target.innerHTML = `<section class="empty-state">\u5546\u54c1\u4e0d\u5b58\u5728</section>`;
    return;
  }
  if (!await ensureCustomerAccess(() => loadDetail(productId))) return;
  await loadDetail(productId);
}

function showStartupError() {
  const target = document.getElementById("productGrid") || document.getElementById("productDetail");
  document.getElementById("inventoryApp")?.removeAttribute("hidden");
  document.getElementById("detailApp")?.removeAttribute("hidden");
  if (target) target.innerHTML = `<section class="empty-state">页面加载失败，请刷新重试</section>`;
}
initListPage().catch(showStartupError);
initDetailPage().catch(showStartupError);
installImageFallbacks();
