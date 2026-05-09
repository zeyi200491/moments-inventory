from moments_inventory.ai_kefu.prompts import build_system_prompt
from moments_inventory.ai_kefu.workflow import WorkflowAnalysis


def test_build_system_prompt_uses_layered_master_rules():
    prompt = build_system_prompt(
        style_guide="语气自然一点，像真人聊天。",
        risk_level="L2",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="推单",
            intent="预算咨询",
            should_handoff=False,
            reply_type="商品推荐",
            required_data=["库存", "预算"],
        ),
        master_rule_guide="先看客户阶段，再决定回复优先级。",
    )

    assert "【最高优先级主规则】" in prompt
    assert "【阶段推进规则】" in prompt
    assert "【固定话术调用规则】" in prompt
    assert "【资料不足兜底规则】" in prompt
    assert "【人工接管触发规则】" in prompt
    assert "【禁止项】" in prompt
    assert "当前客户阶段：推单" in prompt
    assert "当前客户意图：预算咨询" in prompt
    assert "本轮回复类型：商品推荐" in prompt
    assert "本轮必要资料：库存、预算" in prompt
    assert "风险等级：L2" in prompt


def test_build_system_prompt_requires_handoff_and_explicit_fallback():
    prompt = build_system_prompt(
        style_guide="",
        risk_level="L4",
        workflow_analysis=WorkflowAnalysis(
            customer_stage="售后说明",
            intent="售后咨询",
            should_handoff=True,
            reply_type="转人工",
            required_data=["售后规则"],
        ),
        master_rule_guide="售后争议场景优先转人工。",
    )

    assert "是否应转人工：是" in prompt
    assert "本轮必须优先转人工或明确需要人工确认" in prompt
    assert "资料不全、库存不明、价格不明、视频未核实、售后边界不明时" in prompt
    assert "不得直接承诺退款、赔付、最低价、绝对时效或超出知识范围的售后结果" in prompt
