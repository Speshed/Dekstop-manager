from larix_nexus.utils.i18n import TRANSLATIONS_EN, TRANSLATIONS_RU


def test_sync_finished_translation_exists_in_both_languages():
    assert TRANSLATIONS_RU["status.sync_finished"] == "Синхронизация завершена"
    assert TRANSLATIONS_EN["status.sync_finished"] == "Synchronization completed"
