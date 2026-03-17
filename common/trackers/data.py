# -*- coding: utf-8 -*-

from common import config_settings


trackers_api_data = {
    'GEMINI':
        {
            "url": config_settings.tracker_config.Gemini_URL,
            "api_key": config_settings.tracker_config.Gemini_APIKEY,
            "pass_key": config_settings.tracker_config.Gemini_PID,
            "announce": f"{config_settings.tracker_config.Gemini_URL}/announce/{config_settings.tracker_config.Gemini_PID}",
            "source": "Gemini",
        }

}

