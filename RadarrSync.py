import logging
import requests
import json
import configparser
import argparse
from typing import Any

API_PREFIX = "/api/v3/"

class RadarrInstance:
    def __init__(self, name, config_section, source: bool):
        self.name = name
        self.url = config_section["url"]
        self.api_key = config_section["api_key"]

        if not source:
            self.source_profile = int(config_section["source_profile"])
            self.target_profile = int(config_section["target_profile"])
            self.path_from = config_section["path_from"]
            self.path_to = config_section["path_to"]

logger = logging.getLogger(__name__)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="RadarrSync.py",
        description="""Simple script that syncs all movies detected on one
        radarr instance to another""")
    parser.add_argument("--config_file", required=True,
                        help="Relative or absolute path to your config file (See Config.txt for an example)")
    parser.add_argument("--source_section", required=True,
                        help="The section from the config file which you want to treat as the source. Movies on the source"
                             "are copied to all other sections if all conditions are met")
    parser.add_argument("--log_file", default=None,
                        help="Name of the log file you wish to use (if not defined, logs go to stdout)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enables DEBUG level logging")
    return parser.parse_args()

def read_config(config_file: str):
    config = configparser.ConfigParser()
    resp = config.read(config_file)
    if len(resp) < 0:
        try:
            raise SystemExit(f"Error: could not load the config file '{config_file}'")
        except SystemExit as e:
            logger.exception("Error reading config")
            raise e

    return config

def raise_for_status(resp: requests.Response):
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.exception(resp.content)
        raise e

def get_movies(radarr_instance: RadarrInstance, session: requests.Session) -> dict:
    resp = session.get(f"{radarr_instance.url}{API_PREFIX}movie?apikey={radarr_instance.api_key}")
    raise_for_status(resp)
    return resp.json()

def sync_movies_to_target(radarr_target: RadarrInstance, source_movies: list, session: requests.Session):
    """Iterates all movies in source_movies and imports them to the radarr_target if they:
    - Have the profile id that the current radarr target specifies in source_profile
    - Are not already present in the radarr target's library"""
    target_movies = get_movies(radarr_target, session)
    target_movie_ids = [movie["tmdbId"] for movie in target_movies]

    for source_movie in source_movies:
        if source_movie["qualityProfileId"] != radarr_target.source_profile:
            logging.debug(f"Skipping {source_movie['title']}, wanted quality profile {radarr_target.source_profile} found profile {source_movie['profileId']}")
            continue

        if source_movie["tmdbId"] in target_movie_ids:
            logging.debug(f"{source_movie['title']} already in {radarr_target.name} library")
            continue

        path = source_movie["path"]
        path.replace(radarr_target.path_from, radarr_target.path_to)

        # New movie! Sync it across
        payload = {
            "title": source_movie["title"],
            "qualityProfileId": radarr_target.target_profile,
            "titleSlug": source_movie["titleSlug"],
            "tmdbId": source_movie["tmdbId"],
            "monitored": source_movie["monitored"],
            "path": path,
            "minimumAvailability": "released",
            "addOptions": {"searchForMovie": True}
        }
        logger.debug(payload)

        resp = session.post(
            f"{radarr_target.url}{API_PREFIX}movie?apikey={radarr_target.api_key}",
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'})
        raise_for_status(resp)

        logger.info(f"Added movie {source_movie['title']} to {radarr_target.name} server")

def main():
    args = parse_args()
    config = read_config(args.config_file)

    logging.basicConfig(filename=args.log_file, level=logging.DEBUG if args.verbose else logging.INFO)

    radarr_source = RadarrInstance(args.source_section, config[args.source_section], True)
    radarr_targets = [RadarrInstance(section, config[section], False) for section in config.sections() if section != args.source_section]

    session = requests.Session()
    session.trust_env = False  # Disables proxies (Is this needed???)

    source_movies = get_movies(radarr_source, session)

    for radarr_target in radarr_targets:
        logger.debug(f"Syncing movies to target: {radarr_target.name} (url={radarr_target.url})")
        sync_movies_to_target(radarr_target, source_movies, session)

if __name__ == "__main__":
    main()