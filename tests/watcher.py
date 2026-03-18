# -*- coding: utf-8 -*-

import tests
from common.settings import get_watcher_folders
# /* ----------------------------------------------------------------------------------------------- */
force_media = 0

def test_cli_watcher():
    cli_scan = tests.argparse.Namespace(
        watcher=True,
        torrent=False,
        duplicate=False,
        tracker=None,
        force=False,
        noup=False,
        noseed=False,
        cross=False,
        upload=False,
        mt=False,
        notitle=None,
        reseed=False,
    )

    tests.cli.args = cli_scan
    bot = tests.Bot(
        path=r"",  # /**/
        cli=tests.cli.args,
        mode="auto",
        trackers_name_list= ['Gemini']
    )
    watcher_folders = get_watcher_folders(tests.config.user_preferences)
    assert bot.watcher(duration=tests.config.user_preferences.WATCHER_INTERVAL,
                       watcher_folders=watcher_folders,
                       state_dir=str(tests.DEFAULT_JSON_PATH.parent)) == True

