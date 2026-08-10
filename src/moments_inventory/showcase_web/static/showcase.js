const state = {
  products: [],
  query: "",
  brand: "",
  price: "",
};

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

function inPriceRange(product) {
  if (!state.price) return true;
  const [min, max] = state.price.split("-").map((part) => Number.parseInt(part, 10));
  const price = product.displayPrice;
  return Number.isFinite(price) && price >= min && price <= max;
}

function matchesSearch(product) {
  if (!state.query) return true;
  const haystack = [
    product.model,
    product.brand,
    product.displayCopy,
  ].join(" ").toLowerCase();
  return haystack.includes(state.query);
}

function filteredProducts() {
  return state.products
    .filter((product) => !state.brand || product.brand === state.brand)
    .filter(inPriceRange)
    .filter(matchesSearch);
}

function renderBrands() {
  const brandFilter = document.getElementById("brandFilter");
  if (!brandFilter) return;
  const brands = [...new Set(state.products.map((product) => product.brand).filter(Boolean))].sort();
  for (const brand of brands) {
    const option = document.createElement("option");
    option.value = brand;
    option.textContent = brand;
    brandFilter.appendChild(option);
  }
}

function renderProductCard(product) {
  const image = product.coverImagePath
    ? `<img src="/${escapeHtml(product.coverImagePath)}" alt="">`
    : `<div class="product-placeholder" aria-label="暂无机身图"></div>`;
  return `<a class="product-card" href="/product?id=${encodeURIComponent(product.productId)}">
    ${image}
    <div class="product-content">
      <div class="product-title-row">
        <h2>${escapeHtml(product.model)}</h2>
        <div class="price">${priceText(product.displayPrice)}</div>
      </div>
      <div class="meta-row">${escapeHtml(product.brand || "未识别品牌")}</div>
      <p class="copy">${escapeHtml(product.displayCopy || "")}</p>
    </div>
  </a>`;
}

function renderList() {
  const productGrid = document.getElementById("productGrid");
  const emptyState = document.getElementById("emptyState");
  const resultCount = document.getElementById("resultCount");
  if (!productGrid || !emptyState || !resultCount) return;
  const products = filteredProducts();
  resultCount.textContent = `${products.length} 台`;
  productGrid.innerHTML = products.map(renderProductCard).join("");
  emptyState.hidden = products.length !== 0;
}

async function initListPage() {
  const productGrid = document.getElementById("productGrid");
  if (!productGrid) return;
  const response = await fetch("/api/public/products");
  const data = await response.json();
  state.products = Array.isArray(data.products) ? data.products : [];
  renderBrands();
  renderList();

  document.getElementById("searchInput").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderList();
  });
  document.getElementById("brandFilter").addEventListener("change", (event) => {
    state.brand = event.target.value;
    renderList();
  });
  document.getElementById("priceFilter").addEventListener("change", (event) => {
    state.price = event.target.value;
    renderList();
  });
}

function renderDetail(product) {
  const target = document.getElementById("productDetail");
  if (!target) return;
  const images = Array.isArray(product.images) ? product.images : [];
  const imagesHtml = images.length
    ? `<div class="detail-images">${images.map((image) => `<img src="/${escapeHtml(image.imagePath)}" alt="">`).join("")}</div>`
    : `<section class="empty-state">暂无详情图</section>`;
  target.innerHTML = `<article>
    <p class="eyebrow">${escapeHtml(product.brand || "CCD")}</p>
    <h1>${escapeHtml(product.model)}</h1>
    <p class="price">${priceText(product.displayPrice)}</p>
    <p class="copy">${escapeHtml(product.displayCopy || product.rawCopy || "")}</p>
    ${imagesHtml}
  </article>`;
}

async function initDetailPage() {
  const target = document.getElementById("productDetail");
  if (!target) return;
  const productId = new URLSearchParams(window.location.search).get("id");
  if (!productId) {
    target.innerHTML = `<section class="empty-state">商品不存在</section>`;
    return;
  }
  const response = await fetch(`/api/public/products/${encodeURIComponent(productId)}`);
  if (!response.ok) {
    target.innerHTML = `<section class="empty-state">商品不存在或已下架</section>`;
    return;
  }
  renderDetail(await response.json());
}

initListPage();
initDetailPage();
