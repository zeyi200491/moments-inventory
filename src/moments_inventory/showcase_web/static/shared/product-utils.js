/* 客户页与管理页共用的稳定标识、图片地址与差异计算。 */
globalThis.ShowcaseUtils = Object.freeze({
  productKey: (product) => product.publicId || product.productId,
  imageUrl(value) {
    const path = String(value || "").trim();
    if (!path || /^(?!https?:)[a-z][a-z0-9+.-]*:/i.test(path) || path.startsWith("//")) return "";
    return /^https?:\/\//i.test(path) ? path : `/${path.replace(/^\/+/, "")}`;
  },
  changedFields(original, draft) {
    return Object.fromEntries(Object.entries(draft).filter(([key, value]) => JSON.stringify(original[key]) !== JSON.stringify(value)));
  },
  imageVariants(value) {
    const path = String(value || "").replace(/^\/+/, "");
    if (!path || /^https?:\/\//i.test(path)) return "";
    return [480, 960].map((width) => `/api/public/image-variant?path=${encodeURIComponent(path)}&width=${width} ${width}w`).join(", ");
  },
});
