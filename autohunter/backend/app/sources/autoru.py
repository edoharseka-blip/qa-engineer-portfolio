"""Auto.ru: публичного API поиска объявлений для покупателей в документации Яндекса не найдено
(https://yandex.ru/dev/autoru/doc/ru/ описывает API для дилеров/партнёров: управление собственными объявлениями и
справочники). Адаптер — заготовка: без договорённости с владельцем площадки данные не собираются."""
from .base import FetchContext, FetchResult, SourceAdapter, SourceNotConfigured


class AutoRuSource(SourceAdapter):
    name = "autoru"
    title = "Авто.ру (требуется партнёрский доступ)"
    requires_key = True
    status_note = "Не реализован: нет публичного API поиска. Подключите, когда получите официальный доступ."

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def configured(self) -> bool:
        return False

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        raise SourceNotConfigured("Авто.ру: официальный поисковый API недоступен; адаптер не активирован")
