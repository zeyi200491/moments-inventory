from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


CustomerStage = Literal["新客", "推单", "验机", "确认购买", "售后说明"]
CustomerIntent = Literal[
    "新客识别",
    "商品推荐",
    "预算咨询",
    "色调偏好",
    "验机视频",
    "购买流程",
    "砍价",
    "瑕疵咨询",
    "配件咨询",
    "发货咨询",
    "续航咨询",
    "售后咨询",
    "预定咨询",
    "导出照片",
    "其他",
]
ReplyType = Literal["固定话术", "商品推荐", "简短回答", "需查询后回答", "转人工"]


@dataclass(slots=True, frozen=True)
class WorkflowAnalysis:
    customer_stage: CustomerStage
    intent: CustomerIntent
    should_handoff: bool
    reply_type: ReplyType
    required_data: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ConversationWorkflowState:
    conversation_id: str
    customer_stage: CustomerStage
    intent: CustomerIntent
    should_handoff: bool


class WorkflowAnalyzer:
    def analyze(
        self,
        customer_message: str,
        previous_state: ConversationWorkflowState | None = None,
    ) -> WorkflowAnalysis:
        message = self._normalize(customer_message)

        if self._contains_any(message, ("退款", "退货", "退换", "投诉", "赔偿", "被骗", "售后", "质保")):
            return WorkflowAnalysis(
                customer_stage="售后说明",
                intent="售后咨询",
                should_handoff=self._contains_any(message, ("投诉", "赔偿", "被骗")),
                reply_type="转人工" if self._contains_any(message, ("投诉", "赔偿", "被骗")) else "固定话术",
                required_data=["售后规则"],
            )

        if self._contains_any(message, ("怎么付款", "怎么下单", "锁单", "定金", "尾款", "支付方式")):
            return WorkflowAnalysis(
                customer_stage="确认购买",
                intent="购买流程",
                should_handoff=False,
                reply_type="简短回答",
                required_data=["支付方式", "锁单规则"],
            )

        if self._contains_any(message, ("验机视频", "视频", "验机", "看看这台", "这台", "那台")):
            return WorkflowAnalysis(
                customer_stage="验机",
                intent="验机视频",
                should_handoff=False,
                reply_type="需查询后回答",
                required_data=["验机视频", "商品文案"],
            )

        if self._contains_any(message, ("预算", "推荐", "暖色", "冷色", "出片", "喜欢哪种", "有没有现货", "还有吗")):
            intent: CustomerIntent = "商品推荐"
            required_data = ["库存", "预算"]
            if self._contains_any(message, ("预算", "多少", "价位")):
                intent = "预算咨询"
            elif self._contains_any(message, ("暖色", "冷色")):
                intent = "色调偏好"
            elif self._contains_any(message, ("现货", "发货", "多久发")):
                intent = "发货咨询"
                required_data = ["库存", "发货信息"]
            return WorkflowAnalysis(
                customer_stage="推单",
                intent=intent,
                should_handoff=False,
                reply_type="商品推荐" if intent in {"商品推荐", "预算咨询", "色调偏好"} else "需查询后回答",
                required_data=required_data,
            )

        if self._contains_any(message, ("配件", "内存卡", "电池", "续航", "导出")):
            intent: CustomerIntent = "配件咨询"
            required_data = ["配件说明"]
            if self._contains_any(message, ("续航", "电池")):
                intent = "续航咨询"
                required_data = ["电池说明"]
            elif "导出" in message:
                intent = "导出照片"
                required_data = ["导出说明"]
            return WorkflowAnalysis(
                customer_stage="推单",
                intent=intent,
                should_handoff=False,
                reply_type="简短回答",
                required_data=required_data,
            )

        if self._contains_any(message, ("便宜", "优惠", "最低价", "少点", "砍价")):
            return WorkflowAnalysis(
                customer_stage="推单",
                intent="砍价",
                should_handoff=False,
                reply_type="固定话术",
                required_data=["优惠规则"],
            )

        if self._contains_any(message, ("瑕疵", "成色", "外观", "屏幕")):
            return WorkflowAnalysis(
                customer_stage="推单",
                intent="瑕疵咨询",
                should_handoff=False,
                reply_type="固定话术",
                required_data=["商品文案", "验机视频"],
            )

        if self._contains_any(message, ("你好", "在吗", "哈喽", "从闲鱼", "截图")):
            return WorkflowAnalysis(
                customer_stage="新客",
                intent="新客识别",
                should_handoff=False,
                reply_type="固定话术",
                required_data=["来源截图"],
            )

        if previous_state is not None and self._contains_any(message, ("好的", "好", "嗯", "行", "可以", "那就", "就这个")):
            return WorkflowAnalysis(
                customer_stage=previous_state.customer_stage,
                intent=previous_state.intent,
                should_handoff=previous_state.should_handoff,
                reply_type="简短回答",
                required_data=[],
            )

        return WorkflowAnalysis(
            customer_stage=previous_state.customer_stage if previous_state is not None else "推单",
            intent="其他",
            should_handoff=previous_state.should_handoff if previous_state is not None else False,
            reply_type="简短回答",
            required_data=[],
        )

    def _contains_any(self, message: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in message for keyword in keywords)

    def _normalize(self, message: str) -> str:
        return "".join(message.split())
