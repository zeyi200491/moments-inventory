import type { KnowledgeTier } from "./types";

export type StructuredKnowledgeTier = "product_material" | "shipping_info" | "after_sale_doc";

export type StructuredKnowledgeField = {
  key: string;
  label: string;
  placeholder: string;
};

export type StructuredKnowledgeSchema = {
  title: string;
  defaultCategory: string;
  fields: StructuredKnowledgeField[];
};

export const STRUCTURED_KNOWLEDGE_SCHEMAS: Record<
  StructuredKnowledgeTier,
  StructuredKnowledgeSchema
> = {
  product_material: {
    title: "商品素材结构化录入",
    defaultCategory: "商品素材",
    fields: [
      { key: "product_model", label: "型号", placeholder: "例如：Canon G7X2" },
      { key: "material_type", label: "素材类型", placeholder: "例如：样片 / 验机视频 / 文案" },
      { key: "usage_scene", label: "使用场景", placeholder: "例如：朋友圈首图 / 私聊补图" },
      { key: "highlights", label: "素材亮点", placeholder: "例如：夜景样张、成色细节、镜头无霉" },
      { key: "file_refs", label: "文件线索", placeholder: "例如：本地目录或素材编号" },
      { key: "notes", label: "补充备注", placeholder: "例如：优先发首图，再补细节图" },
    ],
  },
  shipping_info: {
    title: "发货信息结构化录入",
    defaultCategory: "供应链发货",
    fields: [
      { key: "supplier_name", label: "供应商", placeholder: "例如：老王" },
      { key: "warehouse_location", label: "仓库位置", placeholder: "例如：深圳华强北" },
      { key: "dispatch_sla", label: "发货时效", placeholder: "例如：24 小时内发出" },
      { key: "delivery_scope", label: "配送范围", placeholder: "例如：全国可发" },
      { key: "exceptions", label: "异常说明", placeholder: "例如：周日只处理加急单" },
      { key: "contact_window", label: "联系时间", placeholder: "例如：09:00-21:00" },
      { key: "notes", label: "补充备注", placeholder: "例如：缺货先确认补货周期" },
    ],
  },
  after_sale_doc: {
    title: "售后文件结构化录入",
    defaultCategory: "正式售后",
    fields: [
      { key: "policy_name", label: "规则名称", placeholder: "例如：七天质量问题处理" },
      { key: "applicable_scope", label: "适用范围", placeholder: "例如：到货七天内非人为故障" },
      { key: "required_evidence", label: "必备凭证", placeholder: "例如：订单号、开箱视频、故障视频" },
      { key: "processing_timeline", label: "处理时效", placeholder: "例如：48 小时内给处理方案" },
      { key: "non_covered_cases", label: "不覆盖情况", placeholder: "例如：进水、摔坏、自行拆机" },
      { key: "escalation_rule", label: "升级条件", placeholder: "例如：高价值订单直接转人工" },
      { key: "notes", label: "补充备注", placeholder: "例如：先安抚，再收集完整凭证" },
    ],
  },
};

export function isStructuredKnowledgeTier(
  knowledgeTier: KnowledgeTier,
): knowledgeTier is StructuredKnowledgeTier {
  return knowledgeTier in STRUCTURED_KNOWLEDGE_SCHEMAS;
}

export function createEmptyStructuredFields(
  knowledgeTier: StructuredKnowledgeTier,
): Record<string, string> {
  return STRUCTURED_KNOWLEDGE_SCHEMAS[knowledgeTier].fields.reduce<Record<string, string>>(
    (result, field) => {
      result[field.key] = "";
      return result;
    },
    {},
  );
}
