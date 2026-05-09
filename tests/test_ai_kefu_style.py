from moments_inventory.ai_kefu.style import StyleProfile, build_style_profile


def test_build_style_profile_detects_warm_tone_and_modal_particles():
    profile = build_style_profile(
        [
            "亲，这边给您安排一下哦",
            "麻烦您稍等哈，我马上帮您看看呢",
        ]
    )

    assert profile.tone == "warm"
    assert profile.uses_modal_particles is True


def test_build_style_profile_detects_short_sentences():
    profile = build_style_profile(
        [
            "有货。",
            "可以拍。",
            "今天发。",
        ]
    )

    assert profile.prefers_short_sentences is True


def test_build_style_profile_keeps_neutral_tone_for_empty_input():
    profile = build_style_profile([])

    assert profile.tone == "neutral"
    assert profile.uses_modal_particles is False
    assert profile.prefers_short_sentences is False


def test_build_style_profile_keeps_neutral_tone_for_plain_messages():
    profile = build_style_profile(
        [
            "库存参数已经整理好了。",
            "发货时间以页面说明为准。",
        ]
    )

    assert profile.tone == "neutral"
    assert profile.uses_modal_particles is False


def test_build_style_profile_does_not_join_markers_across_messages():
    profile = build_style_profile(
        [
            "这",
            "边发货时间更新了",
        ]
    )

    assert profile.tone == "neutral"


def test_build_style_profile_returns_runtime_style_profile_instance():
    profile = build_style_profile(["请稍等"])

    assert isinstance(profile, StyleProfile)
    assert not isinstance(profile, dict)
