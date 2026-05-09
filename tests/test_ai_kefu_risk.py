from moments_inventory.ai_kefu.risk import RiskDecision, RuleBasedRiskClassifier


def test_rule_based_risk_classifier_marks_refund_topic_as_l4():
    classifier = RuleBasedRiskClassifier()

    decision = classifier.classify("这个订单我要退款，不处理我就去投诉")

    assert decision.risk_level == "L4"
    assert "退款" in decision.reason


def test_rule_based_risk_classifier_defaults_to_l1_for_other_topics():
    classifier = RuleBasedRiskClassifier()

    decision = classifier.classify("谢谢，先了解一下")

    assert decision.risk_level == "L1"


def test_rule_based_risk_classifier_prefers_higher_priority_level():
    classifier = RuleBasedRiskClassifier()

    decision = classifier.classify("这个商品现在有现货吗，不行我就申请退款")

    assert decision.risk_level == "L4"
    assert "退款" in decision.reason


def test_rule_based_risk_classifier_marks_process_change_topic_as_l3():
    classifier = RuleBasedRiskClassifier()

    decision = classifier.classify("可以走平台但是不交押金吗")

    assert decision.risk_level == "L3"
    assert "押金" in decision.reason or "平台" in decision.reason
