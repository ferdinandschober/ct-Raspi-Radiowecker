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
    volume = 100
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
            if trackinfo == None:
                return

            # get track image
            trackimages = self._clientRequest("core.library.get_images", {
                "uris": [trackinfo["uri"]]})
            if trackimages == None:
                return

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
        self._clientRequest(method)
        self.getState()

    def play(self):
        if not self.playlist_set:
            self.setAlarmPlaylist()
        if self.shuffle:
            method = "core.tracklist.shuffle"
            self._clientRequest(method)
        method = "core.playback.play"
        self._clientRequest(method)
        self.getState()

    def skip(self):
        self._clientRequest("core.playback.next")

    def back(self):
        self._clientRequest("core.playback.previous")

    def getVolume(self):
        try:
            self.volume = int(self._clientRequest("core.mixer.get_volume"))
            self.muted = bool(self._clientRequest(
                "core.mixer.get_mute"))
        except Exception as e:
            print(e, file=sys.stderr)
            self.volume = 100
            self.muted = False

    def toggleMute(self):
        self._clientRequest("core.mixer.set_mute", {"mute": not self.muted})
        self.muted = bool(self._clientRequest(
            "core.mixer.get_mute"))

    def volup(self):
        self._clientRequest("core.mixer.set_volume", {
                            "volume": self.volume + 10})
        self.getVolume()

    def voldown(self):
        self._clientRequest("core.mixer.set_volume", {
                            "volume": self.volume - 10})
        self.getVolume()

    def getState(self):
        status = self._clientRequest("core.playback.get_state")
        if status == "playing":
            self.playing = True
        else:
            self.playing = False

    def setAlarmPlaylist(self):
        try:
            self.checkAlarmPlaylist()
            self._clientRequest("core.tracklist.clear")
            alarm_playlists = self._getAlarmPlaylists()
            if alarm_playlists == None:
                return
            alarm_playlist = alarm_playlists[0]
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
        playlists = self._getAlarmPlaylists()
        if playlists == None:
            return
        if len(playlists) > 0:
            self.playlist = playlists[0]["uri"]
        else:
            try:
                new = self._clientRequest("core.playlists.create", {
                    "name": "Alarm"
                })
                if new == None:
                    raise Exception("empty json-rpc response")
                self.playlist = new[0]["uri"]
            except Exception as e:
                print(f"Failed to create playlist: {e}", file=sys.stderr)

    def _getAlarmPlaylists(self) -> Optional[List[Dict]]:
        try:
            playlists = self._getPlaylists()
            if playlists == None:
                raise Exception("Could not retrieve playlists")
            playlists = list(filter(lambda x: x["name"] == "Alarm", playlists))
            if len(playlists) == 0:
                raise Exception("No playlist named alarm found!")
            return playlists
        except Exception as e:
            print(f"failed to retrieve alarm playlist: {e}", file=sys.stderr)
            sys.stderr.flush()

    def _getPlaylists(self) -> Optional[List[Dict]]:
        try:
            result = self._clientRequest("core.playlists.as_list")
            if result == None:
                raise Exception("Did not receive a valid response")
            return result
        except Exception as e:
            print(f"Failed to retrieve playlists: {e}", file=sys.stderr)
            sys.stderr.flush()


    def _clientRequest(self, method, params={}) -> Optional[Any]:
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
            return response.json().get("result")

        except Exception as e:
            print(f"post request failed: {e}", file=sys.stderr)
            print(f"payload: {payload}", file=sys.stderr)
            sys.stderr.flush()
            return None


if __name__ == "__main__":
    print("This module cannot be called directly.")
