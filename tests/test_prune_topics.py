from ai_social_content_generator.telegram_bot.users import MAX_TOPICS, _prune_topics


def _topic(idx: int, used: bool = False, has_headlines: bool = True) -> dict:
    headlines = [{"text": f"h{idx}", "used": used}] if has_headlines else []
    return {
        "id": f"topic_{idx}",
        "core_idea": f"idea {idx}",
        "headlines": headlines,
        "generated_at": f"2026-01-01T00:00:{idx:02d}+00:00",
    }


def test_prune_noop_under_cap():
    user_data = {"topics": [_topic(i) for i in range(5)]}
    _prune_topics(user_data)
    assert len(user_data["topics"]) == 5


def test_prune_drops_oldest_unused_first():
    # 30 unused (oldest) + 5 used (newest) = 35; cap is 30 → drop 5 oldest unused
    unused = [_topic(i, used=False) for i in range(30)]
    used = [_topic(i, used=True) for i in range(30, 35)]
    user_data = {"topics": unused + used}

    _prune_topics(user_data)

    assert len(user_data["topics"]) == MAX_TOPICS
    remaining_ids = [t["id"] for t in user_data["topics"]]
    # The 5 oldest unused (0..4) should be gone; used topics retained
    for i in range(5):
        assert f"topic_{i}" not in remaining_ids
    for i in range(30, 35):
        assert f"topic_{i}" in remaining_ids


def test_prune_topic_with_no_headlines_counts_as_unused():
    # An empty-headlines topic should be evictable (treated as unused)
    topics = [_topic(i, used=True) for i in range(MAX_TOPICS)]
    topics.insert(0, _topic(999, has_headlines=False))  # oldest, empty
    user_data = {"topics": topics}

    _prune_topics(user_data)

    assert len(user_data["topics"]) == MAX_TOPICS
    assert all(t["id"] != "topic_999" for t in user_data["topics"])


def test_prune_falls_back_to_oldest_when_all_used():
    # 35 fully-used topics; no unused to evict → fall back to oldest by generated_at
    topics = [_topic(i, used=True) for i in range(35)]
    user_data = {"topics": topics}

    _prune_topics(user_data)

    assert len(user_data["topics"]) == MAX_TOPICS
    remaining_ids = {t["id"] for t in user_data["topics"]}
    for i in range(5):
        assert f"topic_{i}" not in remaining_ids
    for i in range(5, 35):
        assert f"topic_{i}" in remaining_ids
