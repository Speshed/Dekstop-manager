from larix_nexus.utils.helpers import compare_file_states


def _file(**extra):
    value = {"id": "7", "name": "plan.pdf", "path": "Sync", "type": "file", "updatedAt": None}
    value.update(extra)
    return value


def test_version_count_change_is_modified():
    changes = compare_file_states([_file(version_count=1, version_ids=["10"])], [_file(version_count=2, version_ids=["10", "11"])])
    assert len(changes) == 1
    assert changes[0]["type"] == "modified"
    assert changes[0]["version_update"] is True


def test_version_ids_are_order_independent():
    assert compare_file_states([_file(version_count=2, version_ids=["11", "10"])], [_file(version_count=2, version_ids=["10", "11"])]) == []


def test_modified_timestamp_is_modified():
    changes = compare_file_states([_file(modified_ts="old")], [_file(modified_ts="new")])
    assert len(changes) == 1
    assert changes[0]["version_update"] is True


def test_legacy_baseline_does_not_trigger_version_change():
    assert compare_file_states([_file()], [_file(version_count=2, version_ids=["10", "11"], modified_ts="new")]) == []


def test_equal_enriched_states_have_no_change():
    assert compare_file_states([_file(version_count=2, version_ids=["10", "11"], modified_ts="same")], [_file(version_count=2, version_ids=["11", "10"], modified_ts="same")]) == []


def test_different_id_without_version_evidence_is_new():
    changes = compare_file_states(
        [_file(id="old", version_count=0, version_ids=[])],
        [_file(id="new", version_count=0, version_ids=[])],
    )
    assert len(changes) == 1
    assert changes[0]["type"] == "new"
    assert "version_update" not in changes[0]


def test_different_id_with_version_evidence_is_modified():
    changes = compare_file_states(
        [_file(id="old", version_count=1, version_ids=["10"])],
        [_file(id="new", version_count=2, version_ids=["10", "11"])],
    )
    assert len(changes) == 1
    assert changes[0]["type"] == "modified"
    assert changes[0]["version_update"] is True
