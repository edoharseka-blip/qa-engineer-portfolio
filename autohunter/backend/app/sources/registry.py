from ..config import Settings
from .apiad import ApiAdSource
from .autoru import AutoRuSource
from .base import SourceAdapter
from .demo import DemoSource


def build_sources(s: Settings) -> list[SourceAdapter]:
    """Создаёт только включённые источники. Источники с обязательным ключом без ключа не создаются —
    они отображаются в мониторинге как «не настроен»."""
    all_names = {"demo", "apiad_avito", "apiad_drom", "autoru"}
    out: list[SourceAdapter] = []
    queries = [q.strip() for q in s.apiad_queries.split(",") if q.strip()]
    for name in s.enabled_sources:
        if name not in all_names:
            raise ValueError(f"Неизвестный источник в SOURCES_ENABLED: {name}")
        if name == "demo":
            out.append(DemoSource(s.demo_seed, s.demo_initial_listings, s.demo_live))
        elif name in ("apiad_avito", "apiad_drom"):
            out.append(ApiAdSource(name.split("_")[1], s.apiad_api_key, s.apiad_base_url, queries,
                                   s.apiad_min_interval_seconds, s.request_timeout_seconds))
        elif name == "autoru":
            out.append(AutoRuSource(s.autoru_api_key))
    return out
