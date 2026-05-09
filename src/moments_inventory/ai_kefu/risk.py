from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RiskLevel = Literal["L1", "L2", "L3", "L4"]


@dataclass(slots=True, frozen=True)
class RiskDecision:
    risk_level: RiskLevel
    reason: str


class RuleBasedRiskClassifier:
    _RULES: tuple[tuple[RiskLevel, tuple[str, ...]], ...] = (
        ("L4", ("退款", "投诉", "举报", "赔偿")),
        ("L3", ("最低价", "特批", "合同", "发票", "押金", "平台", "退换", "质保")),
        ("L2", ("营业时间", "物流", "发货", "现货", "参数")),
    )

    def classify(self, message: str) -> RiskDecision:
        for risk_level, keywords in self._RULES:
            matched_keywords = [keyword for keyword in keywords if keyword in message]
            if matched_keywords:
                return RiskDecision(
                    risk_level=risk_level,
                    reason=f"命中 {risk_level} 风险关键词: {', '.join(matched_keywords)}",
                )
        return RiskDecision(risk_level="L1", reason="未命中风险关键词")
