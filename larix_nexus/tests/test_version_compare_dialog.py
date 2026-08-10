from larix_nexus.utils.i18n import TRANSLATIONS_EN, TRANSLATIONS_RU


def test_compare_versions_title_is_localized_in_both_languages():
    assert TRANSLATIONS_RU["version.compare_title"] == "Сравнение версий"
    assert TRANSLATIONS_EN["version.compare_title"] == "Compare versions"
