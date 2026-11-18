"""Service wiring: one place that builds the application's collaborating parts.

Tests (and the CLI/web entry points) construct the app through :func:`build_context`
so they can inject a fake tag codec, scanner, or providers without touching the
production wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..contracts import SuggestionProvider
from .backup import BackupManager
from .config import AppConfig
from .events import EventLog
from .ingest import (
    IngestionService,
    Scanner,
    build_providers,
    build_scanner,
)
from .review import ReviewService
from .store import LibraryStore
from .tagio import MutagenTagger, TagCodec
from .taxonomy_service import TaxonomyService
from .util import Clock, utc_now_iso
from .writer import ApplyService


@dataclass
class AppContext:
    config: AppConfig
    store: LibraryStore
    taxonomy: TaxonomyService
    events: EventLog
    codec: TagCodec
    backups: BackupManager
    review: ReviewService
    writer: ApplyService
    ingestion: IngestionService

    def close(self) -> None:
        self.store.close()


def build_context(
    config: AppConfig,
    *,
    codec: TagCodec | None = None,
    scanner: Scanner | None = None,
    providers: Sequence[tuple[str, SuggestionProvider]] | None = None,
    clock: Clock = utc_now_iso,
    run_id_factory=None,
) -> AppContext:
    config.ensure_directories()
    store = LibraryStore(
        config.database_path,
        taxonomy_version=config.taxonomy_version,
        clock=clock,
    )
    taxonomy = TaxonomyService(config.taxonomy_dir, config.taxonomy_version)
    events = EventLog(config.events_path, clock=clock)
    selected_codec = codec or MutagenTagger()
    backups = BackupManager(config, store, selected_codec, clock=clock)
    review = ReviewService(
        store, taxonomy, events, clock=clock, actor=config.actor
    )
    writer = ApplyService(
        config,
        store,
        taxonomy,
        backups,
        selected_codec,
        events,
        clock=clock,
        actor=config.actor,
    )
    ingestion = IngestionService(
        config,
        store,
        taxonomy,
        events,
        scanner=scanner or build_scanner(config, store.connection),
        providers=(
            providers
            if providers is not None
            else build_providers(config, taxonomy, store.connection)
        ),
        clock=clock,
        run_id_factory=run_id_factory,
    )
    return AppContext(
        config=config,
        store=store,
        taxonomy=taxonomy,
        events=events,
        codec=selected_codec,
        backups=backups,
        review=review,
        writer=writer,
        ingestion=ingestion,
    )
