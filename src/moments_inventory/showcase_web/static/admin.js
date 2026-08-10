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
      <div class="admin-image-tools">
        <input class="admin-image-file" type="file" accept="image/jpeg,image/png,image/webp">
        <button class="admin-upload-image" type="button">上传图片</button>
        <button class="admin-load-images" type="button">查看图片</button>
        <div class="admin-image-list"></div>
      </div>
    </article>
  `).join("");
}

async function loadProducts() {
  const data = await requestJson("/api/admin/products");
  renderAdminProducts(Array.isArray(data.products) ? data.products : []);
}

async function uploadImage(productId, file) {
  const form = new FormData();
  form.append("imageType", "detail");
  form.append("file", file);
  const response = await fetch(`/api/admin/products/${encodeURIComponent(productId)}/images`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
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
  if (event.target.classList.contains("admin-upload-image")) {
    const file = row.querySelector(".admin-image-file").files[0];
    if (!file) return;
    await uploadImage(productId, file);
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
