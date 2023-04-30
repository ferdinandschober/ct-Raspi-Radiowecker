from typing import Any, Dict, List, Optional
import typing
import sys
import requests
import json
import shutil
import tempfile
import urllib.request
import threading
import time
import pygame
import traceback

DEFAULT_VOLUME = 50

class MusicPlayer(object):
    trackdata = dict()
    artist = ""
    album = ""
    title = ""
    image = None
    _imageurl = ""
    download_complete = False
    image_cache = {}
    playing = False
    muted = False
    volume = DEFAULT_VOLUME
    trackdata_changed = True
    old_trackimages = None
    old_trackinfo = None
    playlist_set = False

    def __init__(self, hostname="127.0.0.1", port="6680", password="", shuffle=False):
        self.url = "http://"+hostname+":"+port+"/mopidy/rpc"
        self.shuffle = shuffle == "1"
        # print(self.checkAlarmPlaylist())
        self.update_thread = threading.Thread(target=self.updateStatus)
        self.update_thread.daemon = True
        self.update_thread.start()


    def _downloader(self):
        if self._imageurl != None and self._imageurl not in self.image_cache:
            with urllib.request.urlopen(self._imageurl) as response:
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    shutil.copyfileobj(response, tmp_file)
                    self.image_cache[self._imageurl] = tmp_file.name

    def updateStatus(self):
        while True:
            self.updateTrackInfo()
            self.getState()
            self.getVolume()
            time.sleep(1)

    @property
    def imageurl(self):
        return self._imageurl

    @imageurl.setter
    def imageurl(self, url):
        if url != self._imageurl:
            self._imageurl = url
            self._downloader()
            self._t = threading.Thread(
                target=self._downloader)
            self._t.daemon = True
            self._t.start()
            self.image = pygame.Surface((1, 1), flags=pygame.SRCALPHA)
            if self._imageurl != None:
                self.image = pygame.image.load(
                    self.image_cache[self._imageurl])
                self.trackdata_changed = True

    def updateTrackInfo(self):
        try:
            # get current track
            trackinfo = self._clientRequest("core.playback.get_current_track")

            # get track image
            trackimages = self._clientRequest("core.library.get_images", {
                "uris": [trackinfo["uri"]]})

            # dont update if track has not changed
            if self.old_trackinfo == trackinfo and self.old_trackimages == trackimages:
                self.trackdata_changed = False
                return

            # save track
            self.old_trackinfo = trackinfo
            self.old_trackimages = trackimages
            self.trackdata_changed = True

            try:
                self.artist = trackinfo["artists"][0]["name"].strip()
            except:
                self.artist = ""
            try:
                self.title = trackinfo["name"].strip()
            except:
                self.title = ""
            try:
                self.album = trackinfo["album"]["name"].strip()
            except:
                self.album = ""
            try:
                self.imageurl = trackimages[trackinfo["uri"]][0]["uri"]
            except:
                self.imageurl = None

        except Exception:
            print(traceback.format_exc(), file=sys.stderr)
            self.artist = self.album = self.title = ""
            self.imageurl = None

        if self.artist == self.album:
            self.album = ""

    def togglePlay(self):
        if not self.playlist_set:
            self.setAlarmPlaylist()
        if self.playing:
            method = "core.playback.pause"
        else:
            method = "core.playback.play"
        try:
            self._clientRequest(method)
        except Exception as e:
            print(f"failed to toggle playback: {e}", file=sys.stderr)
            sys.stderr.flush()
        self.getState()

    def play(self):
        if not self.playlist_set:
            self.setAlarmPlaylist()
        if self.shuffle:
            method = "core.tracklist.shuffle"
            try:
                self._clientRequest(method)
            except Exception as e:
                print(f"failed to set shuffle: {e}", file=sys.stderr)
                sys.stderr.flush()
        method = "core.playback.play"
        try:
            self._clientRequest(method)
        except Exception as e:
            print(f"failed to resume playback: {e}", file=sys.stderr)
            sys.stderr.flush()
        self.getState()

    def skip(self):
        try:
            self._clientRequest("core.playback.next")
        except Exception as e:
            print(f"failed to select next track: {e}", file=sys.stderr)
            sys.stderr.flush()

    def back(self):
        try:
            self._clientRequest("core.playback.previous")
        except Exception as e:
            print(f"failed to select previous track: {e}", file=sys.stderr)
            sys.stderr.flush()

    def getVolume(self):
        try:
            volume = self._clientRequest("core.mixer.get_volume")
            self.volume = int(volume)
            self.muted = bool(self._clientRequest("core.mixer.get_mute"))
        except Exception as e:
            print(f"failed to get volume: {e}", file=sys.stderr)
            self.volume = DEFAULT_VOLUME
            self.muted = False

    def toggleMute(self):
        try:
            self._clientRequest("core.mixer.set_mute", {"mute": not self.muted})
            self.muted = bool(self._clientRequest("core.mixer.get_mute"))
        except Exception as e:
            print(f"failed to toggle mute: {e}", file=sys.stderr)
            sys.stderr.flush()

    def volup(self):
        try:
            self._clientRequest("core.mixer.set_volume", {
                                "volume": self.volume + 10})
        except Exception as e:
            print(f"failed to set volume: {e}", file=sys.stderr)
            sys.stderr.flush()
        self.getVolume()

    def voldown(self):
        try:
            self._clientRequest("core.mixer.set_volume", {
                                "volume": self.volume - 10})
        except Exception as e:
            print(f"failed to set volume: {e}", file=sys.stderr)
            sys.stderr.flush()
        self.getVolume()

    def getState(self):
        try:
            status = self._clientRequest("core.playback.get_state")
            self.playing = status == "playing"
        except Exception as e:
            print("Failed to get playback state: {e}", file=sys.stderr)
            sys.stderr.flush()

    def setAlarmPlaylist(self):
        try:
            self.checkAlarmPlaylist()
            self._clientRequest("core.tracklist.clear")
            alarm_playlist = self._getAlarmPlaylists()[0]
            alarm_uri = alarm_playlist['uri']

            alarm_tracks = self._clientRequest(
                "core.playlists.get_items", {"uri": alarm_uri})
            if alarm_tracks == None:
                raise Exception(f"failed to retrieve alarm_tracks [uri: {alarm_uri}]")
            print(f"alarm_tracks: {alarm_tracks}", file=sys.stderr)

            alarm_tracks = [ a["uri"] for a in alarm_tracks ]
            print(f"alarm_uris: {alarm_tracks}", file=sys.stderr)
            if self._clientRequest("core.tracklist.add", {'uris': alarm_tracks}) == None:
                print("failed to add track to tracklist", file=sys.stderr)
            self.playlist_set = True
        except Exception as e:
            print(e, file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
        sys.stderr.flush()

    def checkAlarmPlaylist(self):
        try:
            self.playlist = self._getAlarmPlaylists()[0]["uri"]
        except Exception as e:
            print("Could not find alarm playlist: Creating a new one", file=sys.stderr)
            sys.stderr.flush()
            try:
                new = self._clientRequest("core.playlists.create", {
                    "name": "Alarm"
                })
                self.playlist = new[0]["uri"]
            except Exception as e:
                print(f"Failed to create playlist: {e}", file=sys.stderr)

    def _getAlarmPlaylists(self) -> List[Dict]:
        try:
            playlists = self._getPlaylists()
            playlists = list(filter(lambda x: x["name"] == "Alarm", playlists))
            if len(playlists) == 0:
                raise Exception("Could not find a playlist named 'Alarm'")
            return playlists
        except Exception as e:
            raise Exception("Failed to retrieve alarm playlist") from e

    def _getPlaylists(self) -> List[Dict]:
        try:
            return self._clientRequest("core.playlists.as_list")
        except Exception as e:
            raise Exception("Failed to retrieve playlists") from e


    def _clientRequest(self, method, params={}) -> Any:
        headers = {'content-type': 'application/json'}
        payload = {
            "method": method,
            "jsonrpc": "2.0",
            "params": params,
            "id": 1,
        }
        try:
            response = requests.post(
                self.url,
                data=json.dumps(payload),
                headers=headers,
                timeout=1
            )
            response.raise_for_status()
            if response == None:
                raise Exception("empty response")

            response = response.json()
            if response == None:
                raise Exception("empty json response")

            return response

        except Exception as e:
            raise Exception("Post request failed") from e


if __name__ == "__main__":
    print("This module cannot be called directly.")
