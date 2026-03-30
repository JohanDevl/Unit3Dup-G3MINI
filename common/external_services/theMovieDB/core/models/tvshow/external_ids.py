# -*- coding: utf-8 -*-

from dataclasses import dataclass


@dataclass
class ExternalIds:
    id: int
    imdb_id: str | None = None
    freebase_mid: str | None = None
    freebase_id: str | None = None
    tvdb_id: int | None = None
    tvrage_id: int | None = None
