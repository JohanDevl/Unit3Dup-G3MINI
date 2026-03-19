# -*- coding: utf-8 -*-

from datetime import datetime

ANIMATION_GENRE_ID = 16


class MediaResult:
    def __init__(self, result=None, video_id: int = 0, imdb_id = None, trailer_key: str = None,
                 keywords_list: str = None, season_title = None):
        self.result = result
        self.trailer_key = trailer_key
        self.keywords_list = keywords_list
        self.video_id = video_id
        self.imdb_id = imdb_id
        self.season_title = season_title
        self.year = None

        if result:
            try:
                self.year = datetime.strptime(result.get_date(), '%Y-%m-%d').year
            except ValueError:
                pass

    def is_animation(self) -> bool:
        """Check if the TMDB result has the Animation genre (ID 16)."""
        if not self.result:
            return False
        # Search results (Movie/TvShow): genre_ids as list[int]
        if hasattr(self.result, 'genre_ids') and self.result.genre_ids:
            return ANIMATION_GENRE_ID in self.result.genre_ids
        # Details results (MovieDetails/TVShowDetails): genres as list[Genre]
        if hasattr(self.result, 'genres') and self.result.genres:
            return any(g.id == ANIMATION_GENRE_ID for g in self.result.genres)
        return False




