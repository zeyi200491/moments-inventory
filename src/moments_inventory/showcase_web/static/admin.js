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
const bulkPreviewSummary = document.getElementById("bulkPreviewSummary");
const bulkPreviewStatus = document.getElementById("bulkPreviewStatus");
const generateBulkPreviewButton = document.getElementById("generateBulkPreviewButton");
const openBulkConfirmButton = document.getElementById("openBulkConfirmButton");
const exportBulkPreviewButton = document.getElementById("exportBulkPreviewButton");
const bulkConfirmDialog = document.getElementById("bulkConfirmDialog");
const cancelBulkConfirmButton = document.getElementById("cancelBulkConfirmButton");
const bulkConfirmStatus = document.getElementById("bulkConfirmStatus");
const applyBulkButton = document.getElementById("applyBulkButton");
const bulkRecoveryPanel = document.getElementById("bulkRecoveryPanel");
const bulkRecoveryStatus = document.getElementById("bulkRecoveryStatus");
const retryBulkRecoveryButton = document.getElementById("retryBulkRecoveryButton");
const sampleMatchingSummary = document.getElementById("sampleMatchingSummary");
const sampleMatchProductList = document.getElementById("sampleMatchProductList");
const sampleMatchGroupList = document.getElementById("sampleMatchGroupList");
const sampleAssetSearchResults = document.getElementById("sampleAssetSearchResults");
const sampleMatchingStatus = document.getElementById("sampleMatchingStatus");
const importReviewBatchList = document.getElementById("importReviewBatchList");
const importReviewBatchDetail = document.getElementById("importReviewBatchDetail");
const importReviewStatus = document.getElementById("importReviewStatus");
const importReviewConfirmDialog = document.getElementById("importReviewConfirmDialog");
const importReviewConfirmMessage = document.getElementById("importReviewConfirmMessage");
const importReviewConfirmStatus = document.getElementById("importReviewConfirmStatus");
const confirmImportReviewAction = document.getElementById("confirmImportReviewAction");
const PENDING_BULK_STORAGE_KEY = "ccd-admin-pending-bulk-request-v1";

function restorePendingBulkRequest() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(PENDING_BULK_STORAGE_KEY) || "null");
    if (!saved || typeof saved.previewId !== "string" || !saved.previewId ||
        typeof saved.idempotencyKey !== "string" || !saved.idempotencyKey) return null;
    return Object.freeze({ previewId: saved.previewId, idempotencyKey: saved.idempotencyKey });
  } catch (_error) {
    return null;
  }
}

const adminState = {
  products: [],
  sections: [],
  galleryAlbums: [],
  purchaseSteps: [],
  sampleMatchingProducts: [],
  sampleMatchingGroups: [],
  sampleAssets: [],
  sampleProductsHasMore: false,
  sampleGroupsHasMore: false,
  sampleAssetsHasMore: false,
  sampleProductsTotal: null,
  sampleGroupsTotal: null,
  sampleAssetTotal: 0,
  sampleSummaryRequestId: 0,
  sampleProductsRequestId: 0,
  sampleGroupsRequestId: 0,
  sampleAssetsRequestId: 0,
  sectionSearchResults: {},
  productQuery: "",
  selectedProductIds: new Set(),
  visibleProductCount: 80,
  productTotal: 0,
  productHasMore: false,
  lastBulkRequest: null,
  lastBulkPreview: null,
  pendingBulkRequest: restorePendingBulkRequest(),
  drafts: new Map(),
  managementDrafts: new Map(),
  pendingGalleryFiles: new Map(),
  galleryUploads: new Set(),
  settingsDraft: new Map(),
  createSectionSelection: new Set(),
  createFormDirty: new Set(),
  productRequestId: 0,
  productController: null,
  productLoading: false,
  bulkBusy: false,
  previewRequestId: 0,
  previewController: null,
  previewBusy: false,
  bulkAuthExpired: false,
  bulkRecoveryMessage: "",
  bulkRecoveryStorageFailed: false,
  undoKeys: new Map(),
  pendingImageFiles: new Map(),
  imageUploads: new Set(),
  importReviewBatches: [],
  importReviewActiveBatch: null,
  importReviewTargetOptions: new Map(),
  importReviewConfirmAction: null,
  importReviewBusy: false,
};

const ADMIN_PRODUCT_PAGE_SIZE = 80;
const BULK_PRICE_RANGES = {
  all: [null, null],
  up_to_200: [null, 200],
  "201_300": [201, 300],
  "301_600": [301, 600],
  "601_800": [601, 800],
  "801_plus": [801, null],
};
const BULK_FILTER_CONFLICT = "__bulk_filter_conflict__";

function managementRowKey(row) {
  const identities = [
    ["partnerId", "partner"], ["sectionId", "section"], ["itemId", "section-item"],
    ["stepId", "step"], ["albumId", "album"], ["imageId", "gallery-image"],
  ];
  for (const [attribute, type] of identities) {
    if (row?.dataset?.[attribute]) return `${type}:${row.dataset[attribute]}`;
  }
  return "";
}

function rememberManagementRow(row) {
  const key = managementRowKey(row);
  if (!key) return;
  const draft = adminState.managementDrafts.get(key) || {};
  for (const control of row.querySelectorAll("input, textarea, select")) {
    if (control.type === "file") continue;
    const className = String(control.className || control.getAttribute("class") || "").trim().split(/\s+/)[0];
    if (!className) continue;
    draft[className] = control.type === "checkbox" ? control.checked : control.value;
  }
  adminState.managementDrafts.set(key, draft);
}

function restoreManagementRow(row) {
  const draft = adminState.managementDrafts.get(managementRowKey(row));
  if (!draft) return;
  for (const control of row.querySelectorAll("input, textarea, select")) {
    if (control.type === "file") continue;
    const className = String(control.className || control.getAttribute("class") || "").trim().split(/\s+/)[0];
    if (!Object.prototype.hasOwnProperty.call(draft, className)) continue;
    if (control.type === "checkbox") control.checked = draft[className];
    else control.value = draft[className];
  }
}

function clearManagementRowDraft(row, { clearPendingFile = false, clearChildren = false } = {}) {
  const key = managementRowKey(row);
  if (key) adminState.managementDrafts.delete(key);
  if (clearPendingFile && row?.dataset?.albumId) adminState.pendingGalleryFiles.delete(row.dataset.albumId);
  if (clearChildren && row?.dataset?.sectionId) {
    row.querySelectorAll(".section-item-row").forEach((item) => adminState.managementDrafts.delete(managementRowKey(item)));
  }
  if (clearChildren && row?.dataset?.albumId) {
    row.querySelectorAll(".gallery-image-row").forEach((image) => adminState.managementDrafts.delete(managementRowKey(image)));
  }
}

function restoreManagementRows(container, selector) {
  container?.querySelectorAll(selector).forEach(restoreManagementRow);
}

const managementRowSelector = ".partner-admin-row, .section-admin-row, .section-item-row, .purchase-step-admin-row, .gallery-admin-row, .gallery-image-row";
document.addEventListener("input", (event) => {
  const row = event.target.closest?.(managementRowSelector);
  if (row) rememberManagementRow(row);
});
document.addEventListener("change", (event) => {
  const row = event.target.closest?.(managementRowSelector);
  if (row) rememberManagementRow(row);
  if (!event.target.classList.contains("gallery-image-file")) return;
  const albumRow = event.target.closest(".gallery-admin-row");
  if (!albumRow) return;
  const file = event.target.files[0];
  if (file) adminState.pendingGalleryFiles.set(albumRow.dataset.albumId, file);
  else adminState.pendingGalleryFiles.delete(albumRow.dataset.albumId);
  const status = albumRow.querySelector(".gallery-pending-file");
  if (status) status.textContent = file?.name || "";
});
document.getElementById("settingsForm")?.addEventListener("input", (event) => {
  if (["statementInput", "shopIntroInput", "watermarkInput", "inventoryUpdatedInput"].includes(event.target.id)) {
    adminState.settingsDraft.set(event.target.id, event.target.value);
  }
});
window.addEventListener("unhandledrejection", (event) => {
  event.preventDefault();
  const panel = document.getElementById("adminActionError");
  if (!panel) return;
  const error = event.reason || {};
  const message = error.status === 401
    ? "登录已过期，请重新登录；未确认成功的操作请先核对列表。"
    : error.status === 422
      ? "操作内容未通过校验，请检查输入后重试。"
      : error.status >= 500
        ? `服务暂时不可用（${error.status}），请核对操作结果后重试。`
        : `操作失败，请检查网络或输入后重试：${String(error.message || "未知错误").slice(0, 180)}`;
  panel.textContent = message;
  panel.hidden = false;
});
document.addEventListener("input", () => {
  const panel = document.getElementById("adminActionError");
  if (panel) panel.hidden = true;
});
createSectionPicker?.addEventListener("change", () => {
  adminState.createSectionSelection = new Set(
    Array.from(createSectionPicker.querySelectorAll?.(".create-section-checkbox:checked") || [], (input) => input.value)
  );
});
const createFormIds = ["partnerForm", "sectionForm", "galleryForm", "purchaseStepForm", "createProductForm"];
for (const formId of createFormIds) {
  const form = document.getElementById(formId);
  form?.addEventListener("input", () => adminState.createFormDirty.add(formId));
  form?.addEventListener("change", () => adminState.createFormDirty.add(formId));
}
function resetAdminCreateForm(form) {
  form.reset();
  adminState.createFormDirty.delete(form.id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderImportReviewBatches() {
  const batches = Array.isArray(adminState.importReviewBatches) ? adminState.importReviewBatches : [];
  const count = document.getElementById("importReviewPendingCount");
  if (count) count.textContent = String(batches.length);
  if (!importReviewBatchList) return;
  if (!batches.length) {
    importReviewBatchList.innerHTML = '<p class="import-review-muted">当前没有待处理批次。上传工作簿后会出现在这里。</p>';
    return;
  }
  const activeId = adminState.importReviewActiveBatch?.batchId || "";
  importReviewBatchList.innerHTML = batches.map((batch) => `
    <article class="import-review-batch-card" aria-current="${batch.batchId === activeId ? "true" : "false"}">
      <button class="import-review-open-batch" data-batch-id="${escapeHtml(batch.batchId)}" type="button">
        <strong>${escapeHtml(batch.sourceLabel || batch.sourcePath || "未命名工作簿")}</strong>
        <small>${escapeHtml(batch.sourceScope)} · ${batch.mode === "full" ? "全量" : "增量"} · ${Number(batch.parsedRowCount) || 0} 行</small>
        <small>${escapeHtml(batch.createdAt || "")}</small>
      </button>
      <button class="secondary-button import-review-discard-batch" data-batch-id="${escapeHtml(batch.batchId)}" type="button">放弃批次</button>
    </article>
  `).join("");
}

function importReviewRowTargetOptions(row) {
  const saved = adminState.importReviewTargetOptions.get(row.reviewRowId) || [];
  const byId = new Map();
  for (const product of [
    ...(Array.isArray(row.candidates) ? row.candidates : []),
    ...(row.recommendation ? [row.recommendation] : []),
    ...saved,
  ]) {
    const id = String(product.product_id || product.productId || "");
    if (id) byId.set(id, product);
  }
  if (row.productId && !byId.has(String(row.productId))) {
    byId.set(String(row.productId), { product_id: row.productId, model: "当前关联目标", brand: "" });
  }
  return [...byId.values()];
}

function renderImportReviewBatch(batch) {
  adminState.importReviewActiveBatch = batch || null;
  renderImportReviewBatches();
  if (!importReviewBatchDetail) return;
  if (!batch) {
    importReviewBatchDetail.innerHTML = '<p class="import-review-muted">选择左侧批次，继续之前的身份复核。</p>';
    return;
  }
  const rows = Array.isArray(batch.rows) ? batch.rows : [];
  const undecided = rows.filter((row) => !row.decision).length;
  const result = batch.result && typeof batch.result === "object" ? batch.result : {};
  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const missingItems = Array.isArray(result.missing_items) ? result.missing_items : [];
  const isPending = batch.status === "pending";
  const completeLabel = batch.complete ? "已声明完整" : "未声明完整";
  const summary = `
    <div class="import-review-summary">
      <span class="import-review-chip">${batch.mode === "full" ? "全量快照" : "增量导入"}</span>
      <span class="import-review-chip">来源范围：${escapeHtml(batch.sourceScope)}</span>
      <span class="import-review-chip">${escapeHtml(completeLabel)}</span>
      <span class="import-review-chip">待决定 ${undecided} / ${rows.length}</span>
      <span class="import-review-chip">全量缺失 ${Number(batch.missingCount) || 0} 项</span>
    </div>
    ${warnings.map((warning) => `<p class="import-review-warning">${escapeHtml(warning)}</p>`).join("")}
    ${missingItems.length ? `<div><strong>范围内未出现在工作簿的商品</strong><ul class="import-review-missing">${missingItems.slice(0, 20).map((item) => `<li>${escapeHtml(item.brand)} ${escapeHtml(item.model)} <span class="import-review-muted">${escapeHtml(item.product_id)}</span></li>`).join("")}${missingItems.length > 20 ? `<li>另有 ${missingItems.length - 20} 项</li>` : ""}</ul></div>` : ""}
  `;
  const rowHtml = rows.map((row) => {
    const snapshot = row.snapshot && typeof row.snapshot === "object" ? row.snapshot : {};
    const candidates = importReviewRowTargetOptions(row);
    const chosen = String(row.productId || "");
    const errors = Array.isArray(row.errors) ? row.errors : [];
    const candidateSummary = candidates.length
      ? candidates.map((item) => `${item.reason ? `${item.reason} · ` : ""}${item.brand || ""} ${item.model || ""} (${item.product_id || item.productId})`).join("；")
      : "没有现成候选，可搜索库存后选择目标。";
    const rawText = snapshot.raw_copy || snapshot.source_display_copy || snapshot.display_copy || "";
    return `
      <article class="import-review-row" data-review-row-id="${escapeHtml(row.reviewRowId)}" data-row-number="${Number(row.rowNumber) || 0}">
        <div class="import-review-row-head">
          <strong>Excel 第 ${Number(row.rowNumber) || 0} 行 · ${escapeHtml(snapshot.brand)} ${escapeHtml(snapshot.model)}</strong>
          <span class="import-review-chip">${row.decision ? `已决定：${escapeHtml(row.decision)}` : "待决定"}</span>
        </div>
        <p class="import-review-muted">来源商品键：<code>${escapeHtml(row.sourceKey || "（空）")}</code></p>
        ${rawText ? `<details><summary>查看原文</summary><div class="import-review-raw">${escapeHtml(rawText)}</div></details>` : ""}
        ${errors.length ? `<ul class="import-review-errors">${errors.map((error) => `<li>${escapeHtml(error)}</li>`).join("")}</ul>` : ""}
        <p class="import-review-candidates">候选：${escapeHtml(candidateSummary)}</p>
        <div class="import-review-row-grid">
          <label class="field">
            <span>复核决定</span>
            <select class="import-review-decision" ${isPending ? "" : "disabled"}>
              <option value="" ${row.decision ? "" : "selected"}>选择决定</option>
              <option value="link" ${row.decision === "link" ? "selected" : ""}>关联现有商品</option>
              <option value="create" ${row.decision === "create" ? "selected" : ""}>创建新商品</option>
              <option value="skip" ${row.decision === "skip" ? "selected" : ""}>跳过此行</option>
            </select>
          </label>
          <label class="field import-review-target-field" ${row.decision === "link" || !row.decision ? "" : "hidden"}>
            <span>关联目标商品</span>
            <select class="import-review-target" ${isPending ? "" : "disabled"}>
              <option value="">选择商品</option>
              ${candidates.map((item) => {
                const id = String(item.product_id || item.productId || "");
                return `<option value="${escapeHtml(id)}" ${chosen === id ? "selected" : ""}>${escapeHtml(item.brand || "")} ${escapeHtml(item.model || id)} · ${escapeHtml(id)}</option>`;
              }).join("")}
            </select>
          </label>
        </div>
        <div class="import-review-search">
          <label class="field"><span>搜索现有商品</span><input class="import-review-product-query" type="search" placeholder="商品ID、型号或品牌" ${isPending ? "" : "disabled"}></label>
          <button class="secondary-button import-review-search-products" type="button" ${isPending ? "" : "disabled"}>搜索目标</button>
          <button class="access-button import-review-save-decision" type="button" ${isPending ? "" : "disabled"}>保存本行决定</button>
        </div>
      </article>
    `;
  }).join("");
  importReviewBatchDetail.innerHTML = `
    <div class="import-review-heading">
      <div><p class="import-review-kicker">${isPending ? "复核进行中" : "批次已结束"}</p><h3>${escapeHtml(batch.sourceLabel || batch.sourcePath || "导入批次")}</h3><p class="import-review-muted">${escapeHtml(batch.sourcePath || "")} · 创建于 ${escapeHtml(batch.createdAt || "")}</p></div>
      <div class="import-review-row-actions">
        ${isPending ? `<button class="access-button import-review-commit-batch" type="button" ${undecided ? "disabled" : ""}>提交已复核批次</button><button class="secondary-button import-review-discard-active" type="button">放弃批次</button>` : ""}
      </div>
    </div>
    ${summary}
    ${isPending && undecided ? `<p class="status-text">还有 ${undecided} 行需要选择“关联现有商品 / 创建新商品 / 跳过”。完成决定后才可提交。</p>` : ""}
    ${rowHtml || '<p class="import-review-muted">工作簿没有可复核的商品行。</p>'}
    ${batch.status === "committed" ? `<p class="import-review-warning">已提交：新增 ${Number(result.inserted_count) || 0}，更新 ${Number(result.updated_count) || 0}，全量缺失 ${Number(result.missing_count) || 0}。</p>` : ""}
  `;
}

async function loadImportReviewBatches() {
  try {
    const data = await requestJson("/api/admin/import-review/batches");
    adminState.importReviewBatches = Array.isArray(data) ? data : [];
    renderImportReviewBatches();
    const activeId = adminState.importReviewActiveBatch?.batchId;
    if (activeId && adminState.importReviewBatches.some((batch) => batch.batchId === activeId)) {
      await openImportReviewBatch(activeId, { quiet: true });
    }
    if (importReviewStatus && (!importReviewStatus.textContent || importReviewStatus.textContent.startsWith("读取待处理批次失败："))) {
      importReviewStatus.textContent = adminState.importReviewBatches.length
        ? `已恢复 ${adminState.importReviewBatches.length} 个待处理批次。`
        : "待处理列表已刷新。";
    }
  } catch (error) {
    if (importReviewStatus) importReviewStatus.textContent = `读取待处理批次失败：${String(error.message || "请重试").slice(0, 180)}`;
  }
}

async function openImportReviewBatch(batchId, { quiet = false } = {}) {
  try {
    const batch = await requestJson(`/api/admin/import-review/batches/${encodeURIComponent(batchId)}`);
    renderImportReviewBatch(batch);
    if (!quiet && importReviewStatus) importReviewStatus.textContent = `已恢复批次：${batch.sourceLabel || batch.batchId}`;
    return batch;
  } catch (error) {
    if (importReviewStatus) importReviewStatus.textContent = `打开复核批次失败：${String(error.message || "请重试").slice(0, 180)}`;
    throw error;
  }
}

async function saveImportReviewDecision(rowNumber, decisionPayload) {
  const batchId = adminState.importReviewActiveBatch?.batchId;
  if (!batchId) return;
  const decision = decisionPayload?.decision || "";
  const productId = decisionPayload?.productId || "";
  if (!decision || (decision === "link" && !productId)) {
    if (importReviewStatus) importReviewStatus.textContent = "请先选择复核决定；关联现有商品时还要选择目标商品。";
    return;
  }
  try {
    await requestJson(`/api/admin/import-review/batches/${encodeURIComponent(batchId)}/rows/${Number(rowNumber)}`, {
      method: "PUT",
      body: JSON.stringify({ decision, ...(decision === "link" ? { productId } : {}) }),
    });
    await openImportReviewBatch(batchId, { quiet: true });
    if (importReviewStatus) importReviewStatus.textContent = `Excel 第 ${Number(rowNumber)} 行的决定已保存。`;
  } catch (error) {
    if (error.status === 409) {
      await openImportReviewBatch(batchId, { quiet: true }).catch(() => {});
      await loadImportReviewBatches();
      if (importReviewStatus) importReviewStatus.textContent = "批次或目标商品已变化，复核内容已刷新，请重新检查后再保存。";
      return;
    }
    if (importReviewStatus) importReviewStatus.textContent = `保存决定失败：${String(error.message || "请重试").slice(0, 180)}`;
  }
}

function importReviewIdempotencyKey(batchId) {
  const storageKey = `ccd-import-review-commit:${batchId}`;
  try {
    let key = window.localStorage.getItem(storageKey);
    if (!key) {
      key = typeof crypto?.randomUUID === "function" ? crypto.randomUUID() : `review-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      window.localStorage.setItem(storageKey, key);
    }
    return key;
  } catch {
    let key = adminState.importReviewCommitKey;
    if (!key) key = adminState.importReviewCommitKey = `review-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return key;
  }
}

async function commitImportReviewBatch(batchId) {
  if (adminState.importReviewBusy) return;
  adminState.importReviewBusy = true;
  const idempotencyKey = importReviewIdempotencyKey(batchId);
  if (importReviewStatus) importReviewStatus.textContent = "正在提交复核批次…";
  try {
    const result = await requestJson(`/api/admin/import-review/batches/${encodeURIComponent(batchId)}/commit`, {
      method: "POST",
      body: JSON.stringify({ idempotencyKey }),
    });
    await openImportReviewBatch(batchId, { quiet: true });
    await loadImportReviewBatches();
    if (importReviewStatus) {
      importReviewStatus.textContent = `提交已确认：新增 ${Number(result.inserted_count) || 0}，更新 ${Number(result.updated_count) || 0}，缺失 ${Number(result.missing_count) || 0}。`;
    }
  } catch (error) {
    if (error.status === 409) {
      await openImportReviewBatch(batchId, { quiet: true }).catch(() => {});
      await loadImportReviewBatches();
      if (importReviewStatus) importReviewStatus.textContent = "库存或批次版本已变化，复核详情已刷新。请检查未决定行和目标版本后再提交；重试会沿用原幂等键。";
    } else if (importReviewStatus) {
      importReviewStatus.textContent = `提交结果尚未确认，可用同一幂等键重试：${String(error.message || "网络或服务异常").slice(0, 150)}`;
    }
  } finally {
    adminState.importReviewBusy = false;
    renderImportReviewBatch(adminState.importReviewActiveBatch);
  }
}

async function discardImportReviewBatch(batchId) {
  try {
    await requestJson(`/api/admin/import-review/batches/${encodeURIComponent(batchId)}`, { method: "DELETE" });
    if (adminState.importReviewActiveBatch?.batchId === batchId) {
      await openImportReviewBatch(batchId, { quiet: true });
    }
    await loadImportReviewBatches();
    if (importReviewStatus) importReviewStatus.textContent = "复核批次已放弃。";
  } catch (error) {
    if (error.status === 409) {
      await openImportReviewBatch(batchId, { quiet: true }).catch(() => {});
      await loadImportReviewBatches();
      if (importReviewStatus) importReviewStatus.textContent = "批次状态已变化，列表与详情已刷新。";
    } else if (importReviewStatus) {
      importReviewStatus.textContent = `放弃批次失败：${String(error.message || "请重试").slice(0, 180)}`;
    }
  }
}

function openImportReviewConfirmation(action) {
  adminState.importReviewConfirmAction = action;
  const batch = action.batch || adminState.importReviewActiveBatch || {};
  importReviewConfirmMessage.textContent = action.kind === "commit"
    ? `即将按“${batch.sourceScope || "未知来源"}”范围提交此批次。确认前请核对行决定、全量缺失摘要与完整性声明。提交使用可重试的幂等键。`
    : `将放弃“${batch.sourceLabel || "此复核批次"}”并关闭所有待复核行。放弃后不能继续提交。`;
  importReviewConfirmStatus.textContent = "";
  importReviewConfirmStatus.hidden = true;
  confirmImportReviewAction.textContent = action.kind === "commit" ? "确认提交" : "确认放弃";
  importReviewConfirmDialog.showModal();
}

async function searchImportReviewProducts(rowElement) {
  const rowId = rowElement.dataset.reviewRowId;
  const query = rowElement.querySelector(".import-review-product-query")?.value.trim() || "";
  if (!query) {
    if (importReviewStatus) importReviewStatus.textContent = "输入商品ID、型号或品牌后再搜索。";
    return;
  }
  const button = rowElement.querySelector(".import-review-search-products");
  if (button) button.disabled = true;
  try {
    const data = await requestJson(`/api/admin/products?query=${encodeURIComponent(query)}&limit=25&offset=0`);
    adminState.importReviewTargetOptions.set(rowId, Array.isArray(data.products) ? data.products : []);
    await openImportReviewBatch(adminState.importReviewActiveBatch.batchId, { quiet: true });
    if (importReviewStatus) importReviewStatus.textContent = `找到 ${Array.isArray(data.products) ? data.products.length : 0} 个目标候选。`;
  } catch (error) {
    if (importReviewStatus) importReviewStatus.textContent = `搜索商品失败：${String(error.message || "请重试").slice(0, 150)}`;
  } finally {
    if (button) button.disabled = false;
  }
}

const inFlightMutationRequests = new Map();
function bindBusySubmit(form, handler, { busyLabel = "正在提交…" } = {}) {
  if (!form) return;
  let busy = false;
  form.addEventListener("submit", async (event) => {
    if (busy) {
      event.preventDefault();
      return;
    }
    busy = true;
    const button = form.querySelector?.('button[type="submit"], input[type="submit"]');
    const usesValueLabel = String(button?.tagName || "").toUpperCase() === "INPUT";
    const originalLabel = usesValueLabel ? button.value : button?.textContent;
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      if (usesValueLabel) button.value = busyLabel;
      else if ("textContent" in button) button.textContent = busyLabel;
    }
    try {
      await handler(event);
    } finally {
      busy = false;
      if (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        if (typeof originalLabel === "string") {
          if (usesValueLabel) button.value = originalLabel;
          else button.textContent = originalLabel;
        }
      }
    }
  });
}

async function requestJson(url, options = {}, behavior = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const requestKey = method === "GET" || url === "/api/admin/products/bulk-preview" ? "" : `${method}:${url}:${String(options.body || "")}`;
  if (requestKey && inFlightMutationRequests.has(requestKey)) return inFlightMutationRequests.get(requestKey);
  const request = (async () => {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      if (response.status === 401 && url !== "/api/admin/login" && !behavior.deferUnauthorizedUi) {
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
  })();
  if (!requestKey) return request;
  inFlightMutationRequests.set(requestKey, request);
  try {
    return await request;
  } finally {
    if (inFlightMutationRequests.get(requestKey) === request) inFlightMutationRequests.delete(requestKey);
  }
}

const managementMutationLocks = new WeakSet();
async function runManagementMutation(row, button, submit, {
  busyLabel = "正在保存…",
  successMessage = "保存成功。",
  operation = "保存",
  onSuccess,
  refresh,
} = {}) {
  if (!row || !button || button.disabled || managementMutationLocks.has(row)) return false;
  managementMutationLocks.add(row);
  const originalLabel = button.textContent;
  const status = row.querySelector?.(".management-action-status");
  button.disabled = true;
  button.setAttribute?.("aria-busy", "true");
  if (row.setAttribute) row.setAttribute("aria-busy", "true");
  button.textContent = busyLabel;
  if (status) {
    status.textContent = `${operation}中…`;
    status.dataset.state = "busy";
  }

  try {
    const result = await submit();
    if (onSuccess) onSuccess(result);
    if (status) {
      status.textContent = successMessage;
      status.dataset.state = "success";
    }
    if (refresh) {
      try {
        await refresh(result);
      } catch (error) {
        if (status) {
          status.textContent = `${operation}已完成，但页面刷新失败。请重新加载核对当前状态：${String(error.message || "未知错误").slice(0, 120)}`;
          status.dataset.state = "error";
        }
      }
    }
    return true;
  } catch (error) {
    const detail = String(error?.message || "未知错误").slice(0, 140);
    const uncertain = !error?.status || error.status >= 500;
    const message = error?.status === 401
      ? "登录已过期，请重新登录后核对当前状态。"
      : error?.status === 409
        ? `${operation}失败：数据已变化，请刷新后核对再重试。`
        : error?.status === 422
          ? `${operation}失败：输入未通过校验，请修改后重试。${detail}`
          : uncertain
            ? `${operation}结果暂未确认，请先核对列表再决定是否重试。${detail}`
            : `${operation}失败，请检查后重试：${detail}`;
    if (status) {
      status.textContent = message;
      status.dataset.state = "error";
    }
    return false;
  } finally {
    button.disabled = false;
    button.removeAttribute?.("aria-busy");
    button.textContent = typeof originalLabel === "string" ? originalLabel : "保存";
    row.removeAttribute?.("aria-busy");
    managementMutationLocks.delete(row);
  }
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
  const raw = String(document.getElementById(id)?.value ?? "").trim();
  if (raw === "") return null;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : Number.NaN;
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
  if (Number.isFinite(filters.priceMin)) params.set("priceMin", String(filters.priceMin));
  if (Number.isFinite(filters.priceMax)) params.set("priceMax", String(filters.priceMax));
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
  invalidateBulkPreview();
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
        <input class="admin-model-input" aria-label="${escapeHtml(product.model)} 型号" value="${escapeHtml(product.model)}">
        <div class="meta-row">
          ${product.visible ? "展示中" : "已隐藏"} · ${product.sold ? "已售" : "未售"} ·
          ${product.hasBodyImage ? "有机身图" : "无机身图"} ·
          ${product.hasSampleImage ? "有出片图" : "无出片图"} ·
          ${product.manualPrice ? "已改价" : "未改价"} ·
          ${product.reviewState === "missing" ? "来源缺失待复核" : "来源正常"}
        </div>
      </div>
      <input class="admin-brand-input" aria-label="${escapeHtml(product.model)} 品牌" value="${escapeHtml(product.brand)}">
      <input class="admin-price-input" aria-label="${escapeHtml(product.model)} 展示价格" type="number" min="0" value="${product.displayPrice}">
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
        <input class="admin-image-file" aria-label="${escapeHtml(product.model)} 上传商品图片" type="file" accept="image/jpeg,image/png,image/webp">
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
  updateBulkScopeSummary();
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
  if (!adminState.drafts.size && !adminState.pendingImageFiles.size && !adminState.managementDrafts.size && !adminState.pendingGalleryFiles.size && !adminState.settingsDraft.size && !adminState.createFormDirty.size && !adminState.createSectionSelection.size) return;
  event.preventDefault();
  event.returnValue = "";
});

async function loadSettings() {
  const settings = await requestJson("/api/admin/settings");
  const values = {
    statementInput: settings.statementText || "",
    shopIntroInput: settings.shopIntroText || "",
    watermarkInput: settings.watermarkText || "星星CCD",
    inventoryUpdatedInput: settings.inventoryUpdatedAt || "",
  };
  for (const [id, value] of Object.entries(values)) {
    document.getElementById(id).value = adminState.settingsDraft.has(id) ? adminState.settingsDraft.get(id) : value;
  }
  document.getElementById("customerPasswordAdminInput").placeholder = settings.hasCustomerPassword
    ? "已设置，留空则不修改"
    : "还未设置客户口令";
}

function renderPartners(partners) {
  partnerList.innerHTML = partners.map((partner) => `
    <article class="partner-admin-row" data-partner-id="${escapeHtml(partner.partnerId)}">
      <input class="partner-name" aria-label="${escapeHtml(partner.name)} 合作方名称" value="${escapeHtml(partner.name)}">
      <input class="partner-note" aria-label="${escapeHtml(partner.name)} 合作方说明" value="${escapeHtml(partner.note)}">
      <input class="partner-sort" aria-label="${escapeHtml(partner.name)} 排序" type="number" min="0" value="${partner.sortOrder}">
      <label class="check-field">
        <input class="partner-active" type="checkbox" ${partner.active ? "checked" : ""}>
        <span>启用</span>
      </label>
      <button class="partner-save" type="button">保存</button>
      <button class="partner-delete" type="button">删除</button>
      <p class="management-action-status status-text" role="status" aria-live="polite"></p>
    </article>
  `).join("");
  restoreManagementRows(partnerList, ".partner-admin-row");
}

async function loadPartners() {
  const partners = await requestJson("/api/admin/partners");
  renderPartners(Array.isArray(partners) ? partners : []);
}

function renderCreateSectionPicker() {
  if (!createSectionPicker) return;
  const checked = Array.from(createSectionPicker.querySelectorAll?.(".create-section-checkbox:checked") || [], (input) => input.value);
  if (checked.length) adminState.createSectionSelection = new Set(checked);
  const sections = Array.isArray(adminState.sections) ? adminState.sections : [];
  createSectionPicker.innerHTML = sections.length ? sections.map((section) => `
    <label class="section-choice">
      <input class="create-section-checkbox" type="checkbox" value="${escapeHtml(section.sectionId)}" ${adminState.createSectionSelection.has(section.sectionId) ? "checked" : ""}>
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
          <input class="section-item-note" aria-label="${escapeHtml(productLabel)} 专栏推荐语" value="${escapeHtml(item.recommendNote || "")}" placeholder="专区内推荐语">
          <input class="section-item-sort" aria-label="${escapeHtml(productLabel)} 专栏排序" type="number" min="0" value="${item.sortOrder || 0}">
          <button class="section-item-save" type="button">保存</button>
          <button class="section-item-delete" type="button">移除</button>
          <p class="management-action-status status-text" role="status" aria-live="polite"></p>
        </div>
      `;
    }).join("") : `<p class="empty-admin-text">这个专栏还没有商品</p>`;

    return `
      <article class="section-admin-row" data-section-id="${escapeHtml(section.sectionId)}">
        <div class="section-admin-main">
          <input class="section-title" aria-label="专栏名称" value="${escapeHtml(section.title)}">
          <input class="section-subtitle" aria-label="${escapeHtml(section.title)} 说明" value="${escapeHtml(section.subtitle || "")}" placeholder="专栏说明">
          <input class="section-sort" aria-label="${escapeHtml(section.title)} 排序" type="number" min="0" value="${section.sortOrder || 0}">
          <label class="check-field">
            <input class="section-active" type="checkbox" ${section.active ? "checked" : ""}>
            <span>首页展示</span>
          </label>
          <button class="section-save" type="button">保存专栏</button>
          <button class="section-delete" type="button">删除专栏</button>
          <p class="management-action-status status-text" role="status" aria-live="polite"></p>
        </div>
        <div class="section-item-editor section-search-editor">
          <input class="section-product-search-input" type="search" aria-label="在${escapeHtml(section.title)}中搜索型号、品牌或文案" placeholder="搜索型号、品牌、文案">
          <input class="section-product-brand-input" aria-label="${escapeHtml(section.title)}品牌筛选" placeholder="品牌">
          <input class="section-product-min-price" type="number" min="0" aria-label="${escapeHtml(section.title)}最低当前展示价" placeholder="最低价">
          <input class="section-product-max-price" type="number" min="0" aria-label="${escapeHtml(section.title)}最高当前展示价" placeholder="最高价">
          <input class="section-new-note" aria-label="${escapeHtml(section.title)}商品推荐语" placeholder="专区内推荐语">
          <input class="section-new-sort" type="number" min="0" aria-label="${escapeHtml(section.title)}新商品排序" value="0">
          <button class="section-product-search-button" type="button">搜索商品</button>
        </div>
        <div class="section-product-search-results">${renderSectionProductSearchResults(section, searchResults)}</div>
        <div class="section-item-list">${itemHtml}</div>
      </article>
    `;
  }).join("");
  restoreManagementRows(sectionList, ".section-admin-row, .section-item-row");
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
      <input class="purchase-step-title" aria-label="买前流程标题" value="${escapeHtml(step.title)}" placeholder="步骤标题">
      <input class="purchase-step-description" aria-label="${escapeHtml(step.title)} 步骤说明" value="${escapeHtml(step.description || "")}" placeholder="步骤说明">
      <input class="purchase-step-sort" aria-label="${escapeHtml(step.title)} 排序" type="number" min="0" value="${step.sortOrder || 0}">
      <label class="check-field">
        <input class="purchase-step-visible" type="checkbox" ${step.isVisible ? "checked" : ""}>
        <span>客户页展示</span>
      </label>
      <button class="purchase-step-save" type="button">保存</button>
      <button class="purchase-step-delete" type="button">删除</button>
      <p class="management-action-status status-text" role="status" aria-live="polite"></p>
    </article>
  `).join("") : `<p class="empty-admin-text">还没有买前流程步骤</p>`;
  restoreManagementRows(purchaseStepList, ".purchase-step-admin-row");
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
        <input class="gallery-image-caption" aria-label="${escapeHtml(album.title)} 图片说明" value="${escapeHtml(image.caption || "")}" placeholder="图片说明">
        <input class="gallery-image-sort" aria-label="${escapeHtml(album.title)} 图片排序" type="number" min="0" value="${image.sortOrder || 0}">
        <label class="check-field">
          <input class="gallery-image-visible" type="checkbox" ${image.isVisible ? "checked" : ""}>
          <span>展示</span>
        </label>
        <button class="gallery-image-save" type="button">保存</button>
        <button class="gallery-image-up" type="button">上移</button>
        <button class="gallery-image-down" type="button">下移</button>
        <button class="gallery-image-delete" type="button">删除</button>
        <p class="management-action-status status-text" role="status" aria-live="polite"></p>
      </div>
    `).join("") : `<p class="empty-admin-text">这个相册还没有图片</p>`;

    return `
      <article class="gallery-admin-row" data-album-id="${escapeHtml(album.albumId)}">
        <div class="gallery-admin-main">
          <input class="gallery-title" aria-label="相册名称" value="${escapeHtml(album.title)}">
          <input class="gallery-description" aria-label="${escapeHtml(album.title)} 相册说明" value="${escapeHtml(album.description || "")}" placeholder="相册说明">
          <input class="gallery-sort" aria-label="${escapeHtml(album.title)} 排序" type="number" min="0" value="${album.sortOrder || 0}">
          <label class="check-field">
            <input class="gallery-visible" type="checkbox" ${album.isVisible ? "checked" : ""}>
            <span>客户页展示</span>
          </label>
          <button class="gallery-save" type="button">保存相册</button>
          <button class="gallery-delete" type="button">删除相册</button>
          <p class="management-action-status status-text" role="status" aria-live="polite"></p>
        </div>
        <div class="gallery-image-uploader">
          <input class="gallery-image-file" aria-label="${escapeHtml(album.title)} 上传图片" type="file" accept="image/jpeg,image/png,image/webp">
          <span class="gallery-pending-file status-text">${escapeHtml(adminState.pendingGalleryFiles.get(album.albumId)?.name || "")}</span>
          <input class="gallery-image-new-caption" aria-label="${escapeHtml(album.title)}新图片说明" placeholder="图片说明">
          <label class="check-field">
            <input class="gallery-image-new-visible" type="checkbox" checked>
            <span>上传后展示</span>
          </label>
          <button class="gallery-upload-image" type="button">上传图片</button>
          <p class="management-action-status status-text" role="status" aria-live="polite"></p>
        </div>
        <div class="gallery-image-list">${imageHtml}</div>
      </article>
    `;
  }).join("") : `<p class="empty-admin-text">还没有店铺橱窗相册</p>`;
  restoreManagementRows(galleryAlbumList, ".gallery-admin-row, .gallery-image-row");
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
      <span>${escapeHtml(operation.filterText)}</span>
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
        <input class="sample-bind-folder-input" aria-label="${escapeHtml(product.model)} 样片文件夹路径" value="${escapeHtml(product.folderPath || "")}" placeholder="品牌/型号文件夹">
        <button class="sample-bind-product-folder" type="button">绑定</button>
      </div>
    </div>
  `).join("") : `<p class="empty-admin-text">当前筛选下没有商品</p>`;
  const loadMore = document.getElementById("sampleMatchLoadMoreButton");
  if (loadMore) loadMore.hidden = !adminState.sampleProductsHasMore;
  const count = document.getElementById("sampleMatchProductCount");
  if (count) count.textContent = adminState.sampleProductsTotal === null
    ? `已加载 ${products.length} 项${adminState.sampleProductsHasMore ? "，还有更多" : ""}`
    : `共 ${adminState.sampleProductsTotal} 项，已显示 ${products.length} 项`;
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
  const total = document.getElementById("sampleAssetCount");
  if (total) total.textContent = `已显示 ${assets.length} / ${adminState.sampleAssetTotal} 项`;
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
  const loadMore = document.getElementById("sampleGroupLoadMoreButton");
  if (loadMore) loadMore.hidden = !adminState.sampleGroupsHasMore;
  const count = document.getElementById("sampleGroupCount");
  if (count) count.textContent = adminState.sampleGroupsTotal === null
    ? `已加载 ${groups.length} 组${adminState.sampleGroupsHasMore ? "，还有更多" : ""}`
    : `共 ${adminState.sampleGroupsTotal} 组，已显示 ${groups.length} 组`;
}

async function loadSampleMatchingSummary() {
  const requestId = ++adminState.sampleSummaryRequestId;
  const summary = await requestJson("/api/admin/sample-matching/summary");
  if (requestId !== adminState.sampleSummaryRequestId) return;
  renderSampleMatchingSummary(summary);
}

async function loadSampleMatchingProducts({ append = false } = {}) {
  const requestId = ++adminState.sampleProductsRequestId;
  const status = document.getElementById("sampleMatchStatusFilter")?.value || "missing";
  const offset = append ? adminState.sampleMatchingProducts.length : 0;
  const data = await requestJson(`/api/admin/sample-matching/products?status=${encodeURIComponent(status)}&limit=100&offset=${offset}`);
  if (requestId !== adminState.sampleProductsRequestId) return;
  const incoming = Array.isArray(data.products) ? data.products : [];
  adminState.sampleMatchingProducts = append ? [...adminState.sampleMatchingProducts, ...incoming] : incoming;
  adminState.sampleProductsHasMore = Boolean(data.hasMore);
  adminState.sampleProductsTotal = Number.isFinite(data.total) ? Number(data.total) : null;
  renderSampleMatchingProducts();
}

async function loadSampleMatchingGroups({ append = false } = {}) {
  const requestId = ++adminState.sampleGroupsRequestId;
  const offset = append ? adminState.sampleMatchingGroups.length : 0;
  const data = await requestJson(`/api/admin/sample-matching/groups?limit=100&offset=${offset}`);
  if (requestId !== adminState.sampleGroupsRequestId) return;
  const incoming = Array.isArray(data.groups) ? data.groups : [];
  adminState.sampleMatchingGroups = append ? [...adminState.sampleMatchingGroups, ...incoming] : incoming;
  adminState.sampleGroupsHasMore = Boolean(data.hasMore);
  adminState.sampleGroupsTotal = Number.isFinite(data.total) ? Number(data.total) : null;
  renderSampleMatchingGroups();
}

async function loadSampleMatchingCenter() {
  await Promise.all([loadSampleMatchingSummary(), loadSampleMatchingProducts(), loadSampleMatchingGroups()]);
}

async function searchSampleAssets({ append = false } = {}) {
  const requestId = ++adminState.sampleAssetsRequestId;
  const query = document.getElementById("sampleAssetSearchInput")?.value.trim() || "";
  const offset = append ? adminState.sampleAssets.length : 0;
  const data = await requestJson(`/api/admin/sample-matching/assets?query=${encodeURIComponent(query)}&limit=40&offset=${offset}`);
  if (requestId !== adminState.sampleAssetsRequestId) return;
  const incoming = Array.isArray(data.assets) ? data.assets : [];
  adminState.sampleAssets = append ? [...adminState.sampleAssets, ...incoming] : incoming;
  adminState.sampleAssetTotal = Number(data.total || 0);
  adminState.sampleAssetsHasMore = Boolean(data.hasMore);
  renderSampleAssets();
  const loadMore = document.getElementById("sampleAssetLoadMoreButton");
  if (loadMore) loadMore.hidden = !adminState.sampleAssetsHasMore;
}

async function loadAdminApp() {
  loginPanel.hidden = true;
  adminApp.hidden = false;
  const modules = [
    ["设置", loadSettings], ["合作方", loadPartners], ["商品", loadProducts],
    ["买前流程", loadPurchaseStepsAdmin], ["图库", loadGalleryAlbums],
    ["诊断", loadDiagnostics], ["导入记录", loadImportReports], ["操作记录", loadOperations],
    ["样片匹配", loadSampleMatchingCenter], ["专栏", loadSections], ["身份复核", loadImportReviewBatches],
  ];
  const results = await Promise.allSettled(modules.map(([, load]) => load()));
  const failed = results.flatMap((result, index) => result.status === "rejected" ? [modules[index][0]] : []);
  const status = document.getElementById("adminStartupStatus");
  const retryButton = document.getElementById("retryAdminStartupButton");
  status.textContent = failed.length
    ? `管理模块加载失败：${failed.join("、")}。登录已成功，可点击重试加载。`
    : "";
  status.hidden = failed.length === 0;
  retryButton.hidden = failed.length === 0;
}

document.getElementById("retryAdminStartupButton")?.addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  try {
    await loadAdminApp();
  } finally {
    event.currentTarget.disabled = false;
  }
});

let adminSearchTimer;
adminProductSearchInput?.addEventListener("input", (event) => {
  clearTimeout(adminSearchTimer);
  adminState.productController?.abort();
  ++adminState.productRequestId;
  adminState.productQuery = event.target.value.trim().toLowerCase();
  adminState.visibleProductCount = ADMIN_PRODUCT_PAGE_SIZE;
  invalidateBulkPreview();
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
  "adminReviewStateFilterInput",
  "adminTagFilterInput",
]) {
  document.getElementById(id)?.addEventListener("change", () => {
    adminState.visibleProductCount = ADMIN_PRODUCT_PAGE_SIZE;
    adminState.selectedProductIds = new Set();
    invalidateBulkPreview();
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

function adminDeleteConfirmationMessage(button) {
  const product = button.closest(".admin-product-row");
  const section = button.closest(".section-admin-row");
  const item = button.closest(".section-item-row");
  const album = button.closest(".gallery-admin-row");
  const step = button.closest(".purchase-step-admin-row");
  const partner = button.closest(".partner-admin-row");
  const value = (row, selector) => row?.querySelector(selector)?.value?.trim() || "未命名";
  if (button.classList.contains("admin-delete-product")) return `确定删除商品“${value(product, ".admin-model-input")}”吗？此操作会从展示库存中移除该商品。`;
  if (button.classList.contains("section-delete")) return `确定删除专栏“${value(section, ".section-title")}”吗？专栏中的商品关联也会一起移除。`;
  if (button.classList.contains("section-item-delete")) return `确定从专栏中移除“${item?.querySelector("span")?.textContent?.trim() || "该商品"}”吗？`;
  if (button.classList.contains("gallery-delete")) return `确定删除相册“${value(album, ".gallery-title")}”及其中 ${album?.querySelectorAll(".gallery-image-row").length || 0} 张图片吗？`;
  if (button.classList.contains("gallery-image-delete")) return `确定删除相册“${value(album, ".gallery-title")}”中的这张图片吗？`;
  if (button.classList.contains("purchase-step-delete")) return `确定删除买前流程“${value(step, ".purchase-step-title")}”吗？`;
  if (button.classList.contains("partner-delete")) return `确定删除合作方“${value(partner, ".partner-name")}”吗？`;
  if (button.classList.contains("admin-delete-image")) return `确定删除商品“${value(product, ".admin-model-input")}”的一张图片吗？`;
  return "确定执行删除吗？";
}

document.addEventListener("click", (event) => {
  const button = event.target.closest?.(".admin-delete-product, .section-delete, .section-item-delete, .gallery-delete, .gallery-image-delete, .purchase-step-delete, .partner-delete, .admin-delete-image");
  if (!button || window.confirm(adminDeleteConfirmationMessage(button))) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);

bindBusySubmit(loginForm, async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await requestJson("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password: document.getElementById("adminPasswordInput").value }),
    });
  } catch {
    loginError.textContent = "密码错误";
    loginError.hidden = false;
    return;
  }
  await loadAdminApp();
}, { busyLabel: "正在登录…" });

bindBusySubmit(document.getElementById("settingsForm"), async (event) => {
  event.preventDefault();
  document.getElementById("settingsStatus").textContent = "";
  const submittedValues = Object.fromEntries(["statementInput", "shopIntroInput", "watermarkInput", "inventoryUpdatedInput"]
    .map((id) => [id, document.getElementById(id).value]));
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
  for (const [id, submittedValue] of Object.entries(submittedValues)) {
    const currentValue = document.getElementById(id).value;
    if (currentValue === submittedValue) adminState.settingsDraft.delete(id);
    else adminState.settingsDraft.set(id, currentValue);
  }
  document.getElementById("customerPasswordAdminInput").value = "";
  document.getElementById("settingsStatus").textContent = "已保存";
  await loadSettings();
});

bindBusySubmit(document.getElementById("partnerForm"), async (event) => {
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
  resetAdminCreateForm(event.target);
  document.getElementById("partnerActiveInput").checked = true;
  await loadPartners();
});

bindBusySubmit(document.getElementById("sectionForm"), async (event) => {
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
  resetAdminCreateForm(event.target);
  document.getElementById("sectionActiveInput").checked = true;
  await loadSections();
});

bindBusySubmit(document.getElementById("galleryForm"), async (event) => {
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
  resetAdminCreateForm(event.target);
  document.getElementById("galleryVisibleInput").checked = true;
  await loadGalleryAlbums();
});

bindBusySubmit(document.getElementById("purchaseStepForm"), async (event) => {
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
  resetAdminCreateForm(event.target);
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
  try {
    await loadSampleMatchingCenter();
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = "已刷新";
  } catch (error) {
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = "刷新失败，请检查页面错误提示";
    throw error;
  }
});

document.getElementById("rebuildSampleMatchingButton")?.addEventListener("click", async () => {
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在重建";
  try {
    const result = await requestJson("/api/admin/sample-matching/rebuild", { method: "POST" });
    renderSampleMatchingSummary(result.summary || {});
    if (sampleMatchingStatus) {
      const imported = result.importResult || {};
      sampleMatchingStatus.textContent = `已重建：匹配 ${imported.matchedProductCount || 0} 台，写入 ${imported.insertedImageCount || 0} 张`;
    }
    await Promise.all([loadSampleMatchingProducts(), loadProducts(), loadDiagnostics()]);
  } catch (error) {
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = "重建失败，请核对匹配列表后重试";
    throw error;
  }
});

document.getElementById("sampleMatchStatusFilter")?.addEventListener("change", loadSampleMatchingProducts);

document.getElementById("sampleAssetSearchButton")?.addEventListener("click", searchSampleAssets);
document.getElementById("sampleMatchLoadMoreButton")?.addEventListener("click", () => loadSampleMatchingProducts({ append: true }));
document.getElementById("sampleGroupLoadMoreButton")?.addEventListener("click", () => loadSampleMatchingGroups({ append: true }));
document.getElementById("sampleAssetLoadMoreButton")?.addEventListener("click", () => searchSampleAssets({ append: true }));

document.getElementById("sampleAssetSearchInput")?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  searchSampleAssets();
});

sampleAssetSearchResults?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-copy-folder")) return;
  const folderPath = event.target.dataset.folderPath || "";
  if (!folderPath) return;
  const showManualCopy = () => {
    window.prompt("无法自动复制，请手动复制文件夹路径：", folderPath);
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = `请手动复制路径：${folderPath}`;
  };
  if (typeof navigator.clipboard?.writeText !== "function") {
    showManualCopy();
    return;
  }
  try {
    await navigator.clipboard.writeText(folderPath);
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = `已复制：${folderPath}`;
  } catch {
    showManualCopy();
  }
});

sampleMatchProductList?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-bind-product-folder")) return;
  const row = event.target.closest(".sample-match-row");
  const productId = row?.dataset.productId || "";
  const folderPath = row?.querySelector(".sample-bind-folder-input")?.value.trim() || "";
  if (!productId || !folderPath) return;
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在绑定";
  try {
    const result = await requestJson("/api/admin/sample-matching/bind", {
      method: "POST",
      body: JSON.stringify({ productId, folderPath }),
    });
    if (sampleMatchingStatus) {
      const imported = result.importResult || {};
      sampleMatchingStatus.textContent = `已绑定：${result.folderPath}，当前匹配 ${imported.matchedProductCount || 0} 台`;
    }
    await Promise.all([loadSampleMatchingCenter(), loadProducts(), loadDiagnostics()]);
  } catch (error) {
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = "绑定失败，请核对商品匹配状态后重试";
    throw error;
  }
});

sampleMatchGroupList?.addEventListener("click", async (event) => {
  if (!event.target.classList.contains("sample-bind-group")) return;
  const row = event.target.closest(".sample-match-group-row");
  const group = adminState.sampleMatchingGroups[Number(row?.dataset.groupIndex || -1)];
  if (!group || !Array.isArray(group.productIds) || !group.productIds.length) return;
  if (sampleMatchingStatus) sampleMatchingStatus.textContent = "正在批量确认";
  try {
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
  } catch (error) {
    if (sampleMatchingStatus) sampleMatchingStatus.textContent = "批量确认失败，请核对匹配列表后重试";
    throw error;
  }
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
    await runManagementMutation(sectionRow, event.target, () => requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: sectionRow.querySelector(".section-title").value.trim(),
        subtitle: sectionRow.querySelector(".section-subtitle").value.trim(),
        sortOrder: Number(sectionRow.querySelector(".section-sort").value || 0),
        active: sectionRow.querySelector(".section-active").checked,
      }),
    }), {
      operation: "保存专栏",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(sectionRow),
      refresh: loadSections,
    });
  }

  if (event.target.classList.contains("section-delete")) {
    await runManagementMutation(sectionRow, event.target,
      () => requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}`, { method: "DELETE" }), {
        operation: "删除专栏",
        busyLabel: "删除中…",
        successMessage: "专栏已删除。",
        onSuccess: () => clearManagementRowDraft(sectionRow, { clearChildren: true }),
        refresh: loadSections,
      });
  }

  if (event.target.classList.contains("section-product-search-button")) {
    await searchSectionProducts(sectionRow);
    return;
  }

  if (event.target.classList.contains("section-add-search-item")) {
    const resultRow = event.target.closest(".section-product-result");
    const productId = resultRow?.dataset.productId || "";
    if (!productId) return;
    await runManagementMutation(sectionRow, event.target, () => requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items`, {
      method: "POST",
      body: JSON.stringify({
        productId,
        recommendNote: sectionRow.querySelector(".section-new-note").value.trim(),
        sortOrder: Number(sectionRow.querySelector(".section-new-sort").value || 0),
      }),
    }), {
      operation: "添加商品",
      busyLabel: "添加中…",
      successMessage: "商品已加入专栏。",
      onSuccess: () => { adminState.sectionSearchResults[sectionId] = []; },
      refresh: loadSections,
    });
    return;
  }

  const itemRow = event.target.closest(".section-item-row");
  if (!itemRow) return;
  const itemId = itemRow.dataset.itemId;

  if (event.target.classList.contains("section-item-save")) {
    await runManagementMutation(itemRow, event.target, () => requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items/${encodeURIComponent(itemId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        recommendNote: itemRow.querySelector(".section-item-note").value.trim(),
        sortOrder: Number(itemRow.querySelector(".section-item-sort").value || 0),
      }),
    }), {
      operation: "保存专栏商品",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(itemRow),
      refresh: loadSections,
    });
  }

  if (event.target.classList.contains("section-item-delete")) {
    await runManagementMutation(itemRow, event.target,
      () => requestJson(`/api/admin/sections/${encodeURIComponent(sectionId)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE" }), {
        operation: "移除专栏商品",
        busyLabel: "移除中…",
        successMessage: "商品已从专栏移除。",
        onSuccess: () => clearManagementRowDraft(itemRow),
        refresh: loadSections,
      });
  }
});

galleryAlbumList?.addEventListener("click", async (event) => {
  const albumRow = event.target.closest(".gallery-admin-row");
  if (!albumRow) return;
  const albumId = albumRow.dataset.albumId;

  if (event.target.classList.contains("gallery-save")) {
    await runManagementMutation(albumRow, event.target, () => requestJson(`/api/admin/gallery/albums/${encodeURIComponent(albumId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: albumRow.querySelector(".gallery-title").value.trim(),
        description: albumRow.querySelector(".gallery-description").value.trim(),
        sortOrder: Number(albumRow.querySelector(".gallery-sort").value || 0),
        isVisible: albumRow.querySelector(".gallery-visible").checked,
      }),
    }), {
      operation: "保存相册",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(albumRow),
      refresh: loadGalleryAlbums,
    });
  }

  if (event.target.classList.contains("gallery-delete")) {
    await runManagementMutation(albumRow, event.target,
      () => requestJson(`/api/admin/gallery/albums/${encodeURIComponent(albumId)}`, { method: "DELETE" }), {
        operation: "删除相册",
        busyLabel: "删除中…",
        successMessage: "相册及其中图片已删除。",
        onSuccess: () => clearManagementRowDraft(albumRow, { clearPendingFile: true, clearChildren: true }),
        refresh: loadGalleryAlbums,
      });
  }

  if (event.target.classList.contains("gallery-upload-image")) {
    if (adminState.galleryUploads.has(albumId)) return;
    const file = adminState.pendingGalleryFiles.get(albumId) || albumRow.querySelector(".gallery-image-file").files[0];
    if (!file) return;
    adminState.galleryUploads.add(albumId);
    try {
      await runManagementMutation(albumRow, event.target, () => uploadGalleryImage(
        albumId,
        file,
        albumRow.querySelector(".gallery-image-new-caption").value.trim(),
        albumRow.querySelector(".gallery-image-new-visible").checked,
      ), {
        operation: "上传图片",
        busyLabel: "上传中…",
        successMessage: "图片已上传。",
        onSuccess: () => {
          if (adminState.pendingGalleryFiles.get(albumId) === file) adminState.pendingGalleryFiles.delete(albumId);
        },
        refresh: loadGalleryAlbums,
      });
    } finally {
      adminState.galleryUploads.delete(albumId);
    }
  }

  const imageRow = event.target.closest(".gallery-image-row");
  if (!imageRow) return;
  const imageId = imageRow.dataset.imageId;

  if (event.target.classList.contains("gallery-image-save")) {
    await runManagementMutation(imageRow, event.target, () => requestJson(`/api/admin/gallery/images/${encodeURIComponent(imageId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        caption: imageRow.querySelector(".gallery-image-caption").value.trim(),
        sortOrder: Number(imageRow.querySelector(".gallery-image-sort").value || 0),
        isVisible: imageRow.querySelector(".gallery-image-visible").checked,
      }),
    }), {
      operation: "保存图片信息",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(imageRow),
      refresh: loadGalleryAlbums,
    });
  }

  if (event.target.classList.contains("gallery-image-up")) {
    await runManagementMutation(imageRow, event.target,
      () => reorderGalleryImages(albumRow, imageId, -1), {
        operation: "调整图片顺序",
        busyLabel: "调整中…",
        successMessage: "图片顺序已更新。",
        refresh: loadGalleryAlbums,
      });
  }

  if (event.target.classList.contains("gallery-image-down")) {
    await runManagementMutation(imageRow, event.target,
      () => reorderGalleryImages(albumRow, imageId, 1), {
        operation: "调整图片顺序",
        busyLabel: "调整中…",
        successMessage: "图片顺序已更新。",
        refresh: loadGalleryAlbums,
      });
  }

  if (event.target.classList.contains("gallery-image-delete")) {
    await runManagementMutation(imageRow, event.target,
      () => requestJson(`/api/admin/gallery/images/${encodeURIComponent(imageId)}`, { method: "DELETE" }), {
        operation: "删除图片",
        busyLabel: "删除中…",
        successMessage: "图片已删除。",
        onSuccess: () => clearManagementRowDraft(imageRow),
        refresh: loadGalleryAlbums,
      });
  }
});

purchaseStepList?.addEventListener("click", async (event) => {
  const row = event.target.closest(".purchase-step-admin-row");
  if (!row) return;
  const stepId = row.dataset.stepId;

  if (event.target.classList.contains("purchase-step-save")) {
    await runManagementMutation(row, event.target, () => requestJson(`/api/admin/purchase-steps/${encodeURIComponent(stepId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: row.querySelector(".purchase-step-title").value.trim(),
        description: row.querySelector(".purchase-step-description").value.trim(),
        sortOrder: Number(row.querySelector(".purchase-step-sort").value || 0),
        isVisible: row.querySelector(".purchase-step-visible").checked,
      }),
    }), {
      operation: "保存买前步骤",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(row),
      refresh: loadPurchaseStepsAdmin,
    });
  }

  if (event.target.classList.contains("purchase-step-delete")) {
    await runManagementMutation(row, event.target,
      () => requestJson(`/api/admin/purchase-steps/${encodeURIComponent(stepId)}`, { method: "DELETE" }), {
        operation: "删除买前步骤",
        busyLabel: "删除中…",
        successMessage: "步骤已删除。",
        onSuccess: () => clearManagementRowDraft(row),
        refresh: loadPurchaseStepsAdmin,
      });
  }
});

partnerList.addEventListener("click", async (event) => {
  const row = event.target.closest(".partner-admin-row");
  if (!row) return;
  const partnerId = row.dataset.partnerId;
  if (event.target.classList.contains("partner-save")) {
    await runManagementMutation(row, event.target, () => requestJson(`/api/admin/partners/${encodeURIComponent(partnerId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: row.querySelector(".partner-name").value.trim(),
        note: row.querySelector(".partner-note").value.trim(),
        sortOrder: Number(row.querySelector(".partner-sort").value || 0),
        active: row.querySelector(".partner-active").checked,
      }),
    }), {
      operation: "保存合作方",
      busyLabel: "保存中…",
      onSuccess: () => clearManagementRowDraft(row),
      refresh: loadPartners,
    });
  }
  if (event.target.classList.contains("partner-delete")) {
    await runManagementMutation(row, event.target,
      () => requestJson(`/api/admin/partners/${encodeURIComponent(partnerId)}`, { method: "DELETE" }), {
        operation: "删除合作方",
        busyLabel: "删除中…",
        successMessage: "合作方已删除。",
        onSuccess: () => clearManagementRowDraft(row),
        refresh: loadPartners,
      });
  }
});

function nullableBooleanValue(id) {
  const value = document.getElementById(id)?.value ?? "";
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function nonNegativeNumberInputValue(id) {
  const raw = String(document.getElementById(id)?.value ?? "").trim();
  if (raw === "") return null;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : Number.NaN;
}

function selectedBulkPriceRange() {
  const value = document.getElementById("bulkPriceRangeInput")?.value || "all";
  if (value === "custom") {
    return [
      nonNegativeNumberInputValue("bulkMinPriceInput"),
      nonNegativeNumberInputValue("bulkMaxPriceInput"),
    ];
  }
  return BULK_PRICE_RANGES[value] || [null, null];
}

function intersectNullableCondition(left, right) {
  if (left === null) return right;
  if (right === null) return left;
  return left === right ? left : BULK_FILTER_CONFLICT;
}

function buildBulkRequest() {
  const scope = document.getElementById("bulkScopeInput")?.value || "filtered";
  const adminFilters = scope === "filtered" ? collectAdminFilters() : {
    query: "", brands: [], priceMin: null, priceMax: null,
    visible: null, sold: null, hasBodyImage: null,
    hasSampleImage: null, manualPrice: null, reviewState: "", tags: [],
  };
  const { priceMin: displayPriceMin, priceMax: displayPriceMax, ...filters } = adminFilters;
  const [bulkPriceMin, bulkPriceMax] = selectedBulkPriceRange();
  filters.sourcePriceMin = bulkPriceMin;
  filters.sourcePriceMax = bulkPriceMax;
  filters.displayPriceMin = displayPriceMin;
  filters.displayPriceMax = displayPriceMax;
  const bulkVisible = nullableBooleanValue("bulkVisibleInput");
  const bulkSold = nullableBooleanValue("bulkSoldInput");
  if (scope === "filtered") {
    filters.visible = intersectNullableCondition(filters.visible, bulkVisible);
    filters.sold = intersectNullableCondition(filters.sold, bulkSold);
  } else {
    filters.visible = bulkVisible;
    filters.sold = bulkSold;
  }
  return {
    scope,
    operation: document.getElementById("bulkOperationInput")?.value || "price",
    priceMode: document.getElementById("bulkPriceModeInput")?.value || "increment",
    amount: Number(document.getElementById("batchAmountInput")?.value || 0),
    productIds: scope === "selected" ? [...adminState.selectedProductIds] : [],
    filters,
  };
}

function validateBulkRequest(request) {
  if (request.scope === "selected" && request.productIds.length === 0) {
    throw new Error("请先勾选商品，或改用当前筛选结果");
  }
  if (request.filters.visible === BULK_FILTER_CONFLICT) {
    throw new Error("商品筛选与批量面板的展示状态条件没有交集，请调整其中一个条件");
  }
  if (request.filters.sold === BULK_FILTER_CONFLICT) {
    throw new Error("商品筛选与批量面板的已售状态条件没有交集，请调整其中一个条件");
  }
  const hasNarrowingFilter = Boolean(
    request.filters.query || request.filters.brands.length ||
    request.filters.sourcePriceMin !== null || request.filters.sourcePriceMax !== null ||
    request.filters.displayPriceMin !== null || request.filters.displayPriceMax !== null ||
    request.filters.hasBodyImage !== null || request.filters.hasSampleImage !== null ||
    request.filters.manualPrice !== null || request.filters.reviewState || request.filters.tags.length
  );
  if (request.scope === "filtered" && !hasNarrowingFilter) {
    throw new Error("请先选择价格段或设置商品筛选；如需处理全部展示中未售商品，请明确选择全部库存");
  }
  for (const value of [
    request.filters.sourcePriceMin, request.filters.sourcePriceMax,
    request.filters.displayPriceMin, request.filters.displayPriceMax,
  ]) {
    if (value !== null && (!Number.isInteger(value) || value < 0)) {
      throw new Error("价格范围必须填写 0 或正整数");
    }
  }
  const [bulkPriceMin, bulkPriceMax] = selectedBulkPriceRange();
  if (bulkPriceMin !== null && bulkPriceMax !== null && bulkPriceMin > bulkPriceMax) {
    throw new Error("最低价格不能高于最高价格");
  }
  if (request.filters.sourcePriceMin !== null && request.filters.sourcePriceMax !== null &&
      request.filters.sourcePriceMin > request.filters.sourcePriceMax) {
    throw new Error("原价范围无效");
  }
  if (request.filters.displayPriceMin !== null && request.filters.displayPriceMax !== null &&
      request.filters.displayPriceMin > request.filters.displayPriceMax) {
    throw new Error("当前展示价筛选范围无效");
  }
  if (request.operation === "price") {
    if (!Number.isInteger(request.amount) || request.amount < 0) {
      throw new Error("改价金额必须填写 0 或正整数");
    }
    if (request.priceMode !== "fixed_final" && request.amount <= 0) {
      throw new Error("加价或减价金额必须大于 0");
    }
  }
}

function syncBulkControls() {
  const operation = document.getElementById("bulkOperationInput")?.value || "price";
  const priceMode = document.getElementById("bulkPriceModeInput")?.value || "increment";
  const rangeMode = document.getElementById("bulkPriceRangeInput")?.value || "all";
  document.querySelectorAll(".bulk-price-action-field").forEach((field) => {
    field.hidden = operation !== "price";
  });
  const rangeField = document.getElementById("bulkPriceRangeField");
  if (rangeField) rangeField.hidden = false;
  const showCustom = rangeMode === "custom";
  const minField = document.getElementById("bulkCustomMinField");
  const maxField = document.getElementById("bulkCustomMaxField");
  if (minField) minField.hidden = !showCustom;
  if (maxField) maxField.hidden = !showCustom;
  const labels = {
    increment: "每台增加金额",
    decrement: "每台减少金额",
    fixed_final: "新的展示价格",
  };
  const amountLabel = document.getElementById("bulkAmountLabel");
  if (amountLabel) amountLabel.textContent = labels[priceMode] || labels.increment;
}

function formatPriceRange(minimum, maximum) {
  if (Number.isNaN(minimum) || Number.isNaN(maximum)) return "自定义价格区间";
  if (minimum === null && maximum === null) return "全部价格";
  if (minimum === null) return `${maximum} 元以内`;
  if (maximum === null) return `${minimum} 元以上`;
  if (minimum === maximum) return `${minimum} 元`;
  return `${minimum}～${maximum} 元`;
}

function formatBulkPriceRanges(filters) {
  const parts = [];
  if (filters.sourcePriceMin !== null || filters.sourcePriceMax !== null) {
    parts.push(`原价 ${formatPriceRange(filters.sourcePriceMin, filters.sourcePriceMax)}`);
  }
  if (filters.displayPriceMin !== null || filters.displayPriceMax !== null) {
    parts.push(`当前展示价 ${formatPriceRange(filters.displayPriceMin, filters.displayPriceMax)}`);
  }
  return parts.length ? parts.join("；") : "原价不限，当前展示价不限";
}

function updateBulkScopeSummary() {
  const scope = document.getElementById("bulkScopeInput")?.value || "filtered";
  const scopeText = scope === "selected"
    ? `已勾选 ${adminState.selectedProductIds.size} 台商品`
    : scope === "all"
      ? "以全部库存为基础范围"
      : `当前筛选结果共 ${adminState.productTotal} 台`;
  const target = document.getElementById("bulkScopeSummary");
  if (target) {
    const filters = buildBulkRequest().filters;
    target.textContent = `${scopeText} · ${formatBulkPriceRanges(filters)}`;
  }
}

function setBulkPreviewBusy(busy) {
  adminState.previewBusy = busy;
  if (!generateBulkPreviewButton) return;
  generateBulkPreviewButton.disabled = busy;
  generateBulkPreviewButton.textContent = busy ? "预览生成中…" : "生成预览";
}

function updateBulkRecoveryPanel(message = "") {
  const pending = adminState.pendingBulkRequest;
  if (message) adminState.bulkRecoveryMessage = message;
  if (!pending) adminState.bulkRecoveryMessage = "";
  const storageWarning = adminState.bulkRecoveryStorageFailed
    ? "浏览器未能保存会话恢复信息，请勿刷新页面，直到本次操作结果明确。"
    : "";
  if (bulkRecoveryPanel) bulkRecoveryPanel.hidden = !pending;
  if (retryBulkRecoveryButton) retryBulkRecoveryButton.disabled = !pending || adminState.bulkBusy;
  if (pending && openBulkConfirmButton) openBulkConfirmButton.disabled = true;
  if (!pending || !bulkRecoveryStatus) return;
  const status = adminState.bulkBusy
    ? "批量请求仍在后台执行。关闭确认框或调整筛选不会改变这次请求；若最终没有收到结果，可在这里安全重试原请求。"
    : adminState.bulkRecoveryMessage || "上次批量操作结果尚未确认。重试会复用原预览和幂等键，避免重复改价。";
  bulkRecoveryStatus.textContent = [status, storageWarning].filter(Boolean).join(" ");
}

function savePendingBulkRequest(request) {
  adminState.pendingBulkRequest = request ? Object.freeze({
    previewId: request.previewId,
    idempotencyKey: request.idempotencyKey,
  }) : null;
  try {
    if (adminState.pendingBulkRequest) {
      sessionStorage.setItem(PENDING_BULK_STORAGE_KEY, JSON.stringify(adminState.pendingBulkRequest));
    } else {
      sessionStorage.removeItem(PENDING_BULK_STORAGE_KEY);
    }
    adminState.bulkRecoveryStorageFailed = false;
  } catch (_error) {
    adminState.bulkRecoveryStorageFailed = Boolean(adminState.pendingBulkRequest);
  }
  updateBulkRecoveryPanel();
}

function invalidateBulkPreview(message = "条件已变化，请重新生成预览") {
  adminState.previewController?.abort();
  adminState.previewController = null;
  setBulkPreviewBusy(false);
  ++adminState.previewRequestId;
  adminState.lastBulkRequest = null;
  adminState.lastBulkPreview = null;
  if (openBulkConfirmButton) openBulkConfirmButton.disabled = true;
  if (exportBulkPreviewButton) exportBulkPreviewButton.disabled = true;
  if (applyBulkButton) applyBulkButton.disabled = true;
  if (bulkPreviewSummary) bulkPreviewSummary.innerHTML = "";
  if (bulkPreviewPanel) bulkPreviewPanel.innerHTML = "";
  if (bulkPreviewStatus) bulkPreviewStatus.textContent = message;
  updateBulkRecoveryPanel();
}

function renderBulkPreview(preview) {
  if (!bulkPreviewPanel || !bulkPreviewSummary) return;
  const items = Array.isArray(preview.items) ? preview.items : [];
  const stats = preview.priceStats || {};
  const skipReasons = Object.entries(preview.skipReasons || {});
  const unchangedLabel = preview.operation === "price" ? "价格不变" : "状态不变";
  const statCards = [
    ["匹配", preview.matchedCount ?? 0],
    ["实际修改", preview.changedCount ?? 0],
    [unchangedLabel, preview.unchangedCount ?? 0],
    ["跳过", preview.skippedCount ?? 0],
    ["最低新价格", stats.minimum ?? "—"],
    ["最高新价格", stats.maximum ?? "—"],
    ["合计变化", stats.totalDelta ?? 0],
  ].map(([label, value]) => `
    <div class="bulk-preview-stat"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>
  `).join("");
  const skipReasonText = skipReasons.length
    ? skipReasons.map(([reason, count]) => `${escapeHtml(reason)} ${escapeHtml(count)} 台`).join(" · ")
    : "无跳过商品";
  bulkPreviewSummary.innerHTML = `${statCards}<p class="bulk-skip-reasons">跳过原因：${skipReasonText}</p>`;
  bulkPreviewPanel.innerHTML = items.length ? items.map((item) => `
    <div class="admin-compact-row">
      <strong>${escapeHtml(item.model)} · ${escapeHtml(item.brand)}</strong>
      <span>导入价 ${escapeHtml(item.sourcePrice)} · 当前价 ${escapeHtml(item.oldPrice)} → 新价格 ${escapeHtml(item.newPrice)}
        （${item.delta >= 0 ? "+" : ""}${escapeHtml(item.delta)}） ·
        状态 ${item.oldVisible ? "展示" : "隐藏"} → ${item.newVisible ? "展示" : "隐藏"} ·
        ${item.sold ? "已售" : "未售"}
        ${item.skippedReason ? ` · 跳过：${escapeHtml(item.skippedReason)}` : ""}</span>
    </div>
  `).join("") : `<p class="empty-admin-text">当前范围没有可预览的商品</p>`;
  if (bulkPreviewStatus) {
    const displayedCount = preview.displayedCount ?? items.length;
    const expiryText = formatBulkExpiry(preview.expiresAt);
    const validityText = expiryText
      ? `预览将在 ${expiryText} 到期（最长 15 分钟）。`
      : "预览到期时间不可用，请在 15 分钟内完成操作。";
    bulkPreviewStatus.textContent = preview.truncated
      ? `只展示前 ${displayedCount} 台，完整结果请导出 CSV。${validityText}`
      : `已生成 ${preview.matchedCount ?? 0} 台商品的完整预览，${validityText}`;
  }
}

function formatBulkExpiry(expiresAt) {
  const expiry = new Date(expiresAt || "");
  if (Number.isNaN(expiry.getTime())) return "";
  return expiry.toLocaleString("zh-CN", { hour12: false });
}

document.getElementById("batchPriceForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (adminState.bulkBusy) return;
  if (adminState.pendingBulkRequest) {
    updateBulkRecoveryPanel("请先重试或确认上一次批量操作，再生成新的批量预览，避免结果未知时重复改价。");
    bulkRecoveryStatus?.focus();
    return;
  }
  invalidateBulkPreview("正在生成预览…");
  const previewRequestId = adminState.previewRequestId;
  const controller = new AbortController();
  adminState.previewController = controller;
  setBulkPreviewBusy(true);
  try {
    const request = buildBulkRequest();
    validateBulkRequest(request);
    const preview = await requestJson("/api/admin/products/bulk-preview", {
      method: "POST",
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (previewRequestId !== adminState.previewRequestId) return;
    adminState.lastBulkPreview = preview;
    adminState.lastBulkRequest = {
      previewId: preview.previewId,
      idempotencyKey: crypto.randomUUID(),
    };
    renderBulkPreview(preview);
    const canExecute = (preview.changedCount ?? 0) > 0 && Boolean(preview.previewId);
    if (openBulkConfirmButton) {
      openBulkConfirmButton.disabled = !canExecute;
    }
    if (applyBulkButton) applyBulkButton.disabled = !canExecute;
    if (exportBulkPreviewButton) exportBulkPreviewButton.disabled = !preview.previewId;
  } catch (error) {
    if (error.name !== "AbortError" && previewRequestId === adminState.previewRequestId && bulkPreviewStatus) {
      bulkPreviewStatus.textContent = `无法生成预览：${error.message}`;
    }
  } finally {
    if (adminState.previewController === controller) {
      adminState.previewController = null;
      setBulkPreviewBusy(false);
    }
  }
});

for (const id of [
  "bulkScopeInput", "bulkOperationInput", "bulkPriceRangeInput",
  "bulkMinPriceInput", "bulkMaxPriceInput", "bulkVisibleInput",
  "bulkSoldInput", "bulkPriceModeInput", "batchAmountInput",
]) {
  const input = document.getElementById(id);
  const eventName = ["bulkMinPriceInput", "bulkMaxPriceInput", "batchAmountInput"].includes(id)
    ? "input"
    : "change";
  input?.addEventListener(eventName, () => {
    if (id === "bulkOperationInput") {
      const operation = document.getElementById("bulkOperationInput")?.value || "price";
      const visibleInput = document.getElementById("bulkVisibleInput");
      if (visibleInput) visibleInput.value = operation === "show" ? "false" : "true";
    }
    syncBulkControls();
    updateBulkScopeSummary();
    invalidateBulkPreview();
  });
}

document.getElementById("clearBulkSelectionButton")?.addEventListener("click", () => {
  adminState.selectedProductIds = new Set();
  renderAdminProducts();
  updateBulkScopeSummary();
  invalidateBulkPreview("已清空商品选择，请重新生成预览");
});

syncBulkControls();
updateBulkScopeSummary();

function bulkScopeLabel(request) {
  if (request.scope === "selected") return `已勾选 ${request.productIds.length} 台商品`;
  if (request.scope === "all") return "全部库存";
  return "当前筛选结果";
}

function bulkStatusLabel(request) {
  const visible = request.filters.visible === true
    ? "展示中"
    : request.filters.visible === false ? "已隐藏" : "展示中和已隐藏";
  const sold = request.filters.sold === true
    ? "已售"
    : request.filters.sold === false ? "未售" : "未售和已售";
  return `${visible}、${sold}`;
}

function bulkActionLabel(request) {
  if (request.operation === "hide") return "隐藏商品";
  if (request.operation === "show") return "显示商品";
  const labels = {
    increment: "统一加价",
    decrement: "统一减价",
    fixed_final: "固定最终价",
  };
  return `${labels[request.priceMode] || "批量改价"} ${request.amount} 元`;
}

openBulkConfirmButton?.addEventListener("click", () => {
  const preview = adminState.lastBulkPreview;
  if (!preview || !adminState.lastBulkRequest) return;
  const request = buildBulkRequest();
  adminState.bulkAuthExpired = false;
  const warnings = [];
  if (request.scope === "all") {
    warnings.push("本次以全部库存为基础范围。请再次核对价格段和状态条件。");
  }
  if ((preview.changedCount ?? 0) > 200) {
    warnings.push(`本次将修改 ${preview.changedCount} 台商品。`);
  }
  if (request.filters.sold !== false) warnings.push("本次范围可能包含已售商品。");
  if (request.operation === "price" && request.priceMode === "fixed_final" && request.amount === 0) {
    warnings.push("本次会把目标商品价格改为 0 元。");
  }
  const summary = document.getElementById("bulkConfirmSummary");
  const warningList = document.getElementById("bulkConfirmWarnings");
  if (summary) {
    const ruleParts = [
      bulkScopeLabel(request),
      `价格筛选：${formatBulkPriceRanges(request.filters)}`,
      `状态：${bulkStatusLabel(request)}`,
      `动作：${bulkActionLabel(request)}`,
    ];
    const priceStats = preview.priceStats || {};
    if (request.operation === "price" && priceStats.minimum !== null && priceStats.minimum !== undefined &&
        priceStats.maximum !== null && priceStats.maximum !== undefined) {
      ruleParts.push(`实际修改项新价格范围：${formatPriceRange(priceStats.minimum, priceStats.maximum)}`);
    }
    ruleParts.push(`匹配 ${preview.matchedCount ?? 0} 台，实际修改 ${preview.changedCount ?? 0} 台，跳过 ${preview.skippedCount ?? 0} 台`);
    summary.textContent = ruleParts.join(" · ");
  }
  if (warningList) {
    warningList.innerHTML = warnings.length
      ? warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")
      : "<p>未发现额外风险提示，请核对上方数量后执行。</p>";
  }
  if (bulkConfirmStatus) {
    bulkConfirmStatus.textContent = "";
    bulkConfirmStatus.hidden = true;
  }
  if (bulkConfirmDialog) bulkConfirmDialog.returnValue = "";
  bulkConfirmDialog?.showModal();
});

bulkConfirmDialog?.addEventListener("close", () => {
  if (adminState.bulkAuthExpired) {
    adminState.bulkAuthExpired = false;
    adminApp.hidden = true;
    loginPanel.hidden = false;
    loginError.textContent = "登录已过期，请重新登录";
    loginError.hidden = false;
    document.getElementById("adminPasswordInput")?.focus();
    return;
  }
  if (bulkConfirmDialog.returnValue !== "confirm" && (adminState.bulkBusy || adminState.pendingBulkRequest)) {
    updateBulkRecoveryPanel();
    bulkRecoveryStatus?.focus();
    return;
  }
  if (bulkConfirmDialog.returnValue === "confirm" || !adminState.lastBulkRequest) {
    bulkPreviewStatus?.focus();
  } else {
    openBulkConfirmButton?.focus();
  }
});

bulkConfirmDialog?.addEventListener("cancel", (event) => {
  if (!adminState.bulkBusy) return;
  updateBulkRecoveryPanel();
  if (bulkConfirmStatus) {
    bulkConfirmStatus.textContent = "确认框可以关闭，服务器请求会继续执行；如果未收到结果，请使用页面上的“安全重试同一操作”。";
    bulkConfirmStatus.hidden = false;
  }
});

exportBulkPreviewButton?.addEventListener("click", () => {
  const previewId = adminState.lastBulkRequest?.previewId;
  if (!previewId) return;
  window.location.href = `/api/admin/products/bulk-preview/${encodeURIComponent(previewId)}/export`;
});

async function executeBulkRequest(request, recovering = false) {
  if (!request || adminState.bulkBusy) return;
  const stableRequest = adminState.pendingBulkRequest || Object.freeze({
    previewId: request.previewId,
    idempotencyKey: request.idempotencyKey,
  });
  adminState.bulkBusy = true;
  if (!adminState.pendingBulkRequest) savePendingBulkRequest(stableRequest);
  updateBulkRecoveryPanel();
  if (applyBulkButton) applyBulkButton.disabled = true;
  if (retryBulkRecoveryButton) retryBulkRecoveryButton.disabled = true;
  if (cancelBulkConfirmButton) cancelBulkConfirmButton.disabled = false;
  const originalLabel = applyBulkButton?.textContent || "确认执行";
  if (applyBulkButton) applyBulkButton.textContent = "正在执行…";
  try {
    let result;
    try {
      result = await requestJson("/api/admin/products/bulk-apply", {
        method: "POST",
        body: JSON.stringify(stableRequest),
      }, { deferUnauthorizedUi: true });
    } catch (error) {
      const recoverable = !error.status || error.status >= 500 || error.status === 408 || error.status === 429 || (recovering && error.status === 401);
      let message;
      if (recoverable) {
        message = error.status === 401
          ? "登录已过期。请重新登录后，使用页面上的安全重试继续核对这次操作。"
          : error.status === 408
            ? "请求超时（408）。操作结果未知，可安全重试原请求。"
          : error.status === 429
            ? "请求过于频繁。请稍后使用页面上的安全重试继续核对这次操作。"
            : error.status
              ? `服务暂时不可用（${error.status}）。操作结果未知，可安全重试原请求。`
              : `网络连接异常：${error.message}。操作结果未知，可安全重试原请求。`;
        updateBulkRecoveryPanel(message);
        if (error.status === 401) {
          adminApp.hidden = true;
          loginPanel.hidden = false;
          loginError.textContent = "登录已过期，请重新登录后再安全重试上次批量操作";
          loginError.hidden = false;
        }
      } else {
        const messages = {
          401: "登录已过期。请关闭窗口后重新登录，再检查并生成预览。",
          404: "预览不存在或已过期，请重新生成预览。",
          409: "商品数据已经变化，请重新生成预览并核对差异。",
          422: "执行参数已失效，请检查条件后重新生成预览。",
        };
        message = messages[error.status] || `当前预览无法继续执行（${error.status}），请重新生成预览。`;
        savePendingBulkRequest(null);
        adminState.bulkAuthExpired = error.status === 401;
        invalidateBulkPreview(message);
      }
      if (bulkConfirmStatus) {
        bulkConfirmStatus.textContent = message;
        bulkConfirmStatus.hidden = false;
        bulkConfirmStatus.focus();
      }
      if (bulkPreviewStatus && recoverable) bulkPreviewStatus.textContent = message;
      return;
    }

    savePendingBulkRequest(null);
    adminState.lastBulkRequest = null;
    adminState.lastBulkPreview = null;
    adminState.selectedProductIds = new Set();
    if (openBulkConfirmButton) openBulkConfirmButton.disabled = true;
    if (exportBulkPreviewButton) exportBulkPreviewButton.disabled = true;
    if (bulkPreviewStatus) bulkPreviewStatus.textContent = `已执行，实际修改 ${result.updatedCount} 台商品。`;
    bulkConfirmDialog?.close("confirm");
    try {
      await Promise.all([loadProducts(), loadSections(), loadDiagnostics(), loadOperations()]);
    } catch (_refreshError) {
      if (bulkPreviewStatus) {
        bulkPreviewStatus.textContent = "执行已完成，但数据刷新失败，请重新加载页面";
        bulkPreviewStatus.focus();
      }
    }
  } finally {
    adminState.bulkBusy = false;
    if (cancelBulkConfirmButton) cancelBulkConfirmButton.disabled = false;
    if (applyBulkButton) {
      applyBulkButton.disabled = !adminState.lastBulkRequest || Boolean(adminState.pendingBulkRequest);
      applyBulkButton.textContent = originalLabel;
    }
    updateBulkRecoveryPanel();
  }
}

applyBulkButton?.addEventListener("click", async () => {
  if (!adminState.lastBulkRequest || adminState.pendingBulkRequest || adminState.bulkBusy) return;
  await executeBulkRequest(adminState.lastBulkRequest);
});

retryBulkRecoveryButton?.addEventListener("click", async () => {
  if (!adminState.pendingBulkRequest || adminState.bulkBusy) return;
  await executeBulkRequest(adminState.pendingBulkRequest, true);
});

updateBulkRecoveryPanel();

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
  resetAdminCreateForm(event.target);
  adminState.createSectionSelection.clear();
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
    updateBulkScopeSummary();
    invalidateBulkPreview();
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
      const baseline = updated.product || updated;
      adminState.drafts.delete(productId);
      const changes = changedFields(baseline, readProductDraft(row));
      if (Object.keys(changes).length) adminState.drafts.set(productId, { original: baseline, changes });
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
    if (adminState.imageUploads.has(productId)) return;
    const fileInput = row.querySelector(".admin-image-file");
    const file = adminState.pendingImageFiles.get(productId) || fileInput.files[0];
    if (!file) return;
    adminState.imageUploads.add(productId);
    event.target.disabled = true;
    try {
      await uploadImage(productId, file);
      if (adminState.pendingImageFiles.get(productId) === file) adminState.pendingImageFiles.delete(productId);
      if (fileInput.files[0] === file) fileInput.value = "";
      const remainingFile = adminState.pendingImageFiles.get(productId);
      row.querySelector(".admin-pending-file").textContent = remainingFile?.name || "";
      try {
        await loadImages(row);
      } catch {
        row.querySelector(".admin-pending-file").textContent = remainingFile
          ? `${remainingFile.name}（待上传）；图片已上传，列表刷新失败`
          : "图片已上传，但列表刷新失败，请重新加载";
      }
    } catch (error) {
      const remainingFile = adminState.pendingImageFiles.get(productId) || file;
      row.querySelector(".admin-pending-file").textContent = `上传失败，文件已保留，可重试：${remainingFile.name}`;
    } finally {
      adminState.imageUploads.delete(productId);
      event.target.disabled = false;
    }
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

const importReviewUploadForm = document.getElementById("importReviewUploadForm");
const importReviewModeInput = document.getElementById("importReviewModeInput");
const importReviewCompleteField = document.getElementById("importReviewCompleteField");
const importReviewConfirmDialogNode = document.getElementById("importReviewConfirmDialog");

function updateImportReviewModeFields() {
  const isFull = importReviewModeInput?.value === "full";
  if (importReviewCompleteField) importReviewCompleteField.hidden = !isFull;
}

importReviewModeInput?.addEventListener("change", updateImportReviewModeFields);
updateImportReviewModeFields();

importReviewUploadForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (adminState.importReviewBusy) return;
  const button = document.getElementById("uploadImportReviewButton");
  adminState.importReviewBusy = true;
  if (button) {
    button.disabled = true;
    button.textContent = "正在解析工作簿…";
  }
  if (importReviewStatus) importReviewStatus.textContent = "正在上传并建立复核批次；库存不会在此步骤变更。";
  try {
    const response = await fetch("/api/admin/import-review/batches", {
      method: "POST",
      body: new FormData(importReviewUploadForm),
    });
    if (response.status === 401) {
      adminApp.hidden = true;
      loginPanel.hidden = false;
      loginError.textContent = "登录已过期，请重新登录；工作簿需要重新选择后再上传";
      loginError.hidden = false;
    }
    if (!response.ok) {
      const error = new Error(await response.text());
      error.status = response.status;
      throw error;
    }
    const batch = await response.json();
    adminState.importReviewTargetOptions.clear();
    renderImportReviewBatch(batch);
    await loadImportReviewBatches();
    if (importReviewStatus) importReviewStatus.textContent = `工作簿已暂存：${batch.sourceLabel || "复核批次"}。完成逐行决定后再提交。`;
    importReviewUploadForm.querySelector("input[type=file]").value = "";
  } catch (error) {
    if (importReviewStatus) {
      importReviewStatus.textContent = error.status === 400
        ? `工作簿无法解析：${String(error.message || "请检查表头与数据").slice(0, 180)}`
        : `上传失败：${String(error.message || "网络或服务异常").slice(0, 180)}`;
    }
  } finally {
    adminState.importReviewBusy = false;
    if (button) {
      button.disabled = false;
      button.textContent = "上传并开始复核";
    }
  }
});

document.getElementById("refreshImportReviewBatchesButton")?.addEventListener("click", loadImportReviewBatches);
importReviewBatchList?.addEventListener("click", async (event) => {
  const openButton = event.target.closest?.(".import-review-open-batch");
  const discardButton = event.target.closest?.(".import-review-discard-batch");
  if (openButton) await openImportReviewBatch(openButton.dataset.batchId);
  if (discardButton) {
    const batch = adminState.importReviewBatches.find((item) => item.batchId === discardButton.dataset.batchId);
    if (batch) openImportReviewConfirmation({ kind: "discard", batch });
  }
});

importReviewBatchDetail?.addEventListener("change", (event) => {
  if (!event.target.classList.contains("import-review-decision")) return;
  const row = event.target.closest(".import-review-row");
  const targetField = row?.querySelector(".import-review-target-field");
  if (targetField) targetField.hidden = event.target.value !== "link";
});

importReviewBatchDetail?.addEventListener("click", async (event) => {
  const row = event.target.closest?.(".import-review-row");
  if (event.target.closest?.(".import-review-commit-batch")) {
    const batch = adminState.importReviewActiveBatch;
    if (batch) openImportReviewConfirmation({ kind: "commit", batch });
    return;
  }
  if (event.target.closest?.(".import-review-discard-active")) {
    const batch = adminState.importReviewActiveBatch;
    if (batch) openImportReviewConfirmation({ kind: "discard", batch });
    return;
  }
  if (!row) return;
  if (event.target.closest?.(".import-review-search-products")) {
    await searchImportReviewProducts(row);
    return;
  }
  if (event.target.closest?.(".import-review-save-decision")) {
    const decision = row.querySelector(".import-review-decision")?.value || "";
    const productId = row.querySelector(".import-review-target")?.value || "";
    await saveImportReviewDecision(row.dataset.rowNumber, { decision, productId });
  }
});

confirmImportReviewAction?.addEventListener("click", async () => {
  const action = adminState.importReviewConfirmAction;
  if (!action || adminState.importReviewBusy) return;
  const batch = action.batch || adminState.importReviewActiveBatch;
  if (!batch?.batchId) return;
  confirmImportReviewAction.disabled = true;
  try {
    importReviewConfirmDialogNode.close("confirm");
    if (action.kind === "commit") await commitImportReviewBatch(batch.batchId);
    else await discardImportReviewBatch(batch.batchId);
  } finally {
    confirmImportReviewAction.disabled = false;
    adminState.importReviewConfirmAction = null;
  }
});

importReviewConfirmDialog?.addEventListener("close", () => {
  if (importReviewConfirmDialog.returnValue !== "confirm") adminState.importReviewConfirmAction = null;
});

loadImportReviewBatches();
