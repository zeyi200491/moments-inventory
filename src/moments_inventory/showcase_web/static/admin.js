const loginPanel = document.getElementById("loginPanel");
const adminApp = document.getElementById("adminApp");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const adminProductList = document.getElementById("adminProductList");

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
    throw new Error(await response.text());
  }
  return response.json();
}

function renderAdminProducts(products) {
  adminProductList.innerHTML = products.map((product) => `
    <article class="admin-product-row" data-product-id="${escapeHtml(product.productId)}" data-visible="${product.visible ? "true" : "false"}">
      <div>
        <strong>${escapeHtml(product.model)}</strong>
        <div class="meta-row">${escapeHtml(product.brand)} · ${product.visible ? "展示中" : "已隐藏"}</div>
      </div>
      <input class="admin-price-input" type="number" min="0" value="${product.displayPrice}">
      <button class="admin-save-price" type="button">改价</button>
      <button class="admin-toggle-visible" type="button">${product.visible ? "隐藏" : "显示"}</button>
      <button class="admin-delete-product" type="button">删除</button>
    </article>
  `).join("");
}

async function loadProducts() {
  const data = await requestJson("/api/admin/products");
  renderAdminProducts(Array.isArray(data.products) ? data.products : []);
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password: document.getElementById("adminPasswordInput").value }),
    });
    loginPanel.hidden = true;
    adminApp.hidden = false;
    await loadProducts();
  } catch {
    loginError.textContent = "密码错误";
    loginError.hidden = false;
  }
});

document.getElementById("batchPriceForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await requestJson("/api/admin/products/batch-price", {
    method: "POST",
    body: JSON.stringify({
      mode: "increment",
      amount: Number(document.getElementById("batchAmountInput").value || 0),
      brand: document.getElementById("batchBrandInput").value.trim() || null,
    }),
  });
  await loadProducts();
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
      displayCopy: document.getElementById("createCopyInput").value.trim(),
    }),
  });
  event.target.reset();
  await loadProducts();
});

adminProductList.addEventListener("click", async (event) => {
  const row = event.target.closest(".admin-product-row");
  if (!row) return;
  const productId = row.dataset.productId;
  if (event.target.classList.contains("admin-save-price")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, {
      method: "PATCH",
      body: JSON.stringify({ displayPrice: Number(row.querySelector(".admin-price-input").value || 0) }),
    });
    await loadProducts();
  }
  if (event.target.classList.contains("admin-toggle-visible")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, {
      method: "PATCH",
      body: JSON.stringify({ visible: row.dataset.visible !== "true" }),
    });
    await loadProducts();
  }
  if (event.target.classList.contains("admin-delete-product")) {
    await requestJson(`/api/admin/products/${encodeURIComponent(productId)}`, { method: "DELETE" });
    await loadProducts();
  }
});
