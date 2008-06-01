# -*- coding: ISO-8859-1 -*-
#===============================================================================
# VLC Player Plugin by A. L�tsch 2007
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2, or (at your option) any later
# version.
#===============================================================================

from enigma import iPlayableServicePtr
from time import time
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.InfoBarGenerics import InfoBarNotifications, InfoBarAudioSelection
from Components.config import config
from enigma import eServiceReference
from Components.Sources.Source import Source
from Components.ServiceEventTracker import ServiceEventTracker
from enigma import iPlayableService
from enigma import eTimer
from Components.ActionMap import ActionMap
from VlcControlHttp import VlcControlHttp
import re

DEFAULT_VIDEO_PID = 0x44
DEFAULT_AUDIO_PID = 0x45

try:
	import servicets
except Exception, e:
	ENIGMA_SERVICE_ID = 0x1001
	STOP_BEFORE_UNPAUSE = True
	print "[VLC] use Gstreamer", e
else:
	ENIGMA_SERVICE_ID = 0x1002
	STOP_BEFORE_UNPAUSE = False
	print "[VLC] use servicets.so"

def isDvdUrl(url):
	return url.startswith("dvd://") or url.startswith("dvdsimple://")

def splitDvdUrl(url):
	pos = url.rfind("@", len(url)-8)
	if pos > 0:
		track = url[pos+1:]
		url = url[0:pos]
		if track.find(":") >= 0:
			track, chapter = track.split(":")
		else:
			chapter = None
	else:
		track, chapter = (None, None)
	return (url, track, chapter)

class VlcService(Source, iPlayableServicePtr):
	refreshInterval = 3000
	
	class Info:
		def __init__(self, name=""):
			self.name = name
		def getName(self):
			return self.name
		def getInfoObject(self, *args, **kwargs):
			return { }
		def getInfo(self, what):
			return -1
		def getInfoString(self, *args, **kwargs):
			return self.name
		def isPlayable(self):
			return True
		def getEvent(self, what):
			return None

	def __init__(self, player):
		Source.__init__(self)
		self.__info = VlcService.Info()
		self.vlccontrol = None
		self.service = self
		self.player = player
		self.lastrefresh = time()
		self.stats = None
		self.refreshTimer = eTimer()
		self.refreshTimer.timeout.get().append(self.__onRefresh)
		self.refreshTimer.start(self.refreshInterval)
	
	def setFilename(self, filename):
		i = filename.rfind("/")
		if i >= 0:
			filename = filename[i+1:]
		i = filename.rfind("\\")
		if i >= 0:
			filename = filename[i+1:]
		self.__info.name = filename
		self.setChanged()
	
	def setChanged(self):
		self.changed( (self.CHANGED_SPECIFIC, iPlayableService.evStart) )
	
	def setControl(self, control):
		self.vlccontrol = control
		
	def __onRefresh(self):
		if self.vlccontrol is None: 
			self.stats = None
			return
		print "[VLC] refresh"
		try:
			self.stats = self.vlccontrol.status()
			self.lastrefresh = time()
		except Exception, e:
			print e
	
	def refresh(self):
		self.__onRefresh()
	
	def info(self):
		return self.__info
	
	# iSeekableService
	def seek(self):
		return self
	def getPlayPosition(self):
		if self.stats and self.stats.has_key("time"):
			pos = float(self.stats["time"])
			if self.player.state == VlcPlayer.STATE_PLAYING:
				pos += time() - self.lastrefresh
			return (False, int(pos*90000))
		else:
			return (True, 0)
	
	def getLength(self):
		if self.stats and self.stats.has_key("length"):
			return (False, int(self.stats["length"])*90000)
		else:
			return (True, 0)
	
	# iPlayableService
	def cueSheet(self): return None
	def pause(self): return self.player
	def audioTracks(self): 
		return self.player.audioTracks();
	def audioChannel(self): return None
	def subServices(self): return None
	def frontendInfo(self): return None
	def timeshift(self): return None
	def subtitle(self): return None
	def audioDelay(self): return None
	def rdsDecoder(self): return None
	def stream(self): return None
	def start(self):
		self.player.play()
	def stop(self):
		self.player.stop()

class VlcPlayer(Screen, InfoBarNotifications, InfoBarAudioSelection):
	screen_timeout = 5000
	
	STATE_IDLE = 0
	STATE_PLAYING = 1
	STATE_PAUSED = 2
	
	def __init__(self, session, vlcfilelist):
		Screen.__init__(self, session)
		InfoBarNotifications.__init__(self)
		InfoBarAudioSelection.__init__(self)
		self.filelist = vlcfilelist
		self.skinName = "MoviePlayer"
		self.state = self.STATE_IDLE
		self.url = None
		self.oldservice = self.session.screen["CurrentService"]
		self.vlcservice = VlcService(self)
		self["CurrentService"] = self.vlcservice
		self.session.screen["CurrentService"] = self.vlcservice
		self.hidetimer = eTimer()
		self.hidetimer.timeout.get().append(self.ok)
		self.onClose.append(self.__onClose)

		class VlcPlayerActionMap(ActionMap):
			def __init__(self, player, contexts = [ ], actions = { }, prio=0):
				ActionMap.__init__(self, contexts, actions, prio)
				self.player = player
				
			def action(self, contexts, action):
				if action[:5] == "seek:":
					time = int(action[5:])
					self.player.seekRelative(time)
					return 1
				elif action[:8] == "seekdef:":
					key = int(action[8:])
					time = [-config.seek.selfdefined_13.value, False, config.seek.selfdefined_13.value,
							-config.seek.selfdefined_46.value, False, config.seek.selfdefined_46.value,
							-config.seek.selfdefined_79.value, False, config.seek.selfdefined_79.value][key-1]
					self.player.seekRelative(time)
					return 1
				else:
					return ActionMap.action(self, contexts, action)
		
		self["actions"] = VlcPlayerActionMap(self, ["OkCancelActions", "TvRadioActions", "InfobarSeekActions", "MediaPlayerActions"],
		{
				"ok": self.ok,
				"cancel": self.cancel,
				"keyTV": self.stop,
				"pauseService": self.pause,
				"unPauseService": self.play,
				"seekFwd": self.seekFwd,
				"seekBack": self.seekBack,
				"seekFwdDown": self.seekFwd,
				"seekBackDown": self.seekBack,
				"next": self.playNextFile,
				"previous": self.playPrevFile
			}, -2)

		print "evEOF=%d" % iPlayableService.evEOF
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evEOF: self.__evEOF,
#				iPlayableService.evSOF: self.__evSOF,
			})
	def __onClose(self):
		self.session.screen["CurrentService"] = self.oldservice
	
	def __evEOF(self):
		print "[VLC] Event EOF"
		self.stop()
	
	def playfile(self, servernum, path):
		if self.state != self.STATE_IDLE:
			self.stop()

		cfg = config.plugins.vlcplayer.servers[servernum]
		self.vlccontrol = VlcControlHttp(servernum)
		streamName = VlcControlHttp.defaultStreamName
		self.vlcservice.setFilename(path)
		
		self.servernum = servernum
		self.url = "http://%s:%d/%s.ts" % (cfg.host.value, cfg.httpport.value, streamName)
		if path.lower().endswith(".iso") and not isDvdUrl(path):
			self.filename = "dvdsimple://" + path
		else:
			self.filename = path

		do_direct = isDvdUrl(self.filename) or re.match("(?i).*\.(mpg|mpeg|ts)$", self.filename)
		if do_direct and config.plugins.vlcplayer.notranscode.value:
			self.output = "#"
		else:
			transcode = "vcodec=%s,vb=%d,venc=ffmpeg{strict-rc=1},width=%s,height=%s,fps=%s,scale=1,acodec=%s,ab=%d,channels=%d,samplerate=%s" % (
				config.plugins.vlcplayer.vcodec.value, 
				config.plugins.vlcplayer.vb.value, 
				config.plugins.vlcplayer.width.value, 
				config.plugins.vlcplayer.height.value, 
				config.plugins.vlcplayer.fps.value, 
				config.plugins.vlcplayer.acodec.value, 
				config.plugins.vlcplayer.ab.value, 
				config.plugins.vlcplayer.channels.value,
				config.plugins.vlcplayer.samplerate.value
			)
			if config.plugins.vlcplayer.aspect.value != "none":
				transcode += ",canvas-width=%s,canvas-height=%s,canvas-aspect=%s" % (
					config.plugins.vlcplayer.width.value, 
					config.plugins.vlcplayer.height.value, 
					config.plugins.vlcplayer.aspect.value
				) 
			if config.plugins.vlcplayer.soverlay.value:
				transcode += ",soverlay"
			self.output = "#transcode{%s}:" % transcode
		mux="ts{pid-video=%d,pid-audio=%d}" % (DEFAULT_VIDEO_PID, DEFAULT_AUDIO_PID)
		self.output = self.output + "std{access=http,mux=%s,dst=/%s.ts} :sout-all" % (mux, streamName)
		self.play()

	def play(self):
		if self.state == self.STATE_PAUSED:
			self.unpause()
			return
		elif self.state == self.STATE_IDLE and self.url is not None:
			print "[VLC] setupStream: " + self.filename + " " + self.output
			try:
				self.vlccontrol.playfile(self.filename, self.output)
			except Exception, e:
				self.session.open(
					MessageBox, _("Error with VLC server:\n%s" % e), MessageBox.TYPE_ERROR)
				return
			sref = eServiceReference(ENIGMA_SERVICE_ID, 0, self.url)
			print "sref valid=", sref.valid()
			sref.setData(0, DEFAULT_VIDEO_PID)
			sref.setData(1, DEFAULT_AUDIO_PID)
			self.session.nav.playService(sref)
			self.state = self.STATE_PLAYING
			if self.shown:
				self.__setHideTimer()
		self.vlcservice.setControl(self.vlccontrol)
		self.vlcservice.refresh()

	def pause(self):
		print "[VLC] pause"
		if self.state == self.STATE_PLAYING:
			self.session.nav.pause(True)
			self.vlccontrol.pause()
			self.state = self.STATE_PAUSED
			self.vlcservice.refresh()
			if not self.shown:
				self.hidetimer.stop()
				self.show()
		elif self.state == self.STATE_PAUSED:
			self.unpause()

	def unpause(self):
		print "[VLC] unpause"
		try:
			self.vlccontrol.seek("-2")
			self.vlccontrol.play()
		except Exception, e:
			self.session.open(
				MessageBox, _("Error with VLC server:\n%s" % e), MessageBox.TYPE_ERROR)
			self.stop()
			return
		if STOP_BEFORE_UNPAUSE:
			self.session.nav.stopService()
			sref = eServiceReference(ENIGMA_SERVICE_ID, 0, self.url)
			sref.setData(0, DEFAULT_VIDEO_PID)
			sref.setData(1, DEFAULT_AUDIO_PID)
			self.session.nav.playService(sref)
		else:
			self.session.nav.pause(False)
		self.state = self.STATE_PLAYING
		self.vlcservice.refresh()
		if self.shown:
			self.__setHideTimer()
		
	def stop(self):
		print "[VLC] stop"
		self.session.nav.stopService()
		if self.state == self.STATE_IDLE:
			self.close()
			return
		if self.vlccontrol is not None:
			try:
				self.vlccontrol.stop()
				self.vlccontrol.delete()
			except Exception, e:
				self.session.open(
					MessageBox, _("Error with VLC server:\n%s" % e), MessageBox.TYPE_ERROR)
		self.state = self.STATE_IDLE
		self.vlcservice.setControl(None)
		self.vlcservice.refresh()
		self.show()

	def __setHideTimer(self):
		self.hidetimer.start(self.screen_timeout)

	def ok(self):
		if self.shown:
			self.hide()
			self.hidetimer.stop()
			self.vlcservice.refreshTimer.stop()
		else:
			self.vlcservice.refresh()
			self.show()
			if self.state == self.STATE_PLAYING:
				self.__setHideTimer()
			else:
				self.vlcservice.refreshTimer.start(self.vlcservice.refreshInterval)

	def cancel(self):
		self.stop()
		self.close()
	
	def playNextFile(self):
		print "[VLC] playNextFile",self.filename
		if isDvdUrl(self.filename):
			url,track,chapter = splitDvdUrl(self.filename)
			if track is None:
				track = 2
			else:
				track = int(track) + 1
			url = "%s@%d" % (url, track)
			self.playfile(self.servernum, url)
		else:
			path = self.filelist.getNextFile()
			if path is None:
				self.session.open(MessageBox, _("No more files in this directory"), MessageBox.TYPE_INFO)
			else:
				servernum, path = path.split(":", 1)
				self.playfile(int(servernum), path)

	def playPrevFile(self):
		print "[VLC] playPrevFile"
		if isDvdUrl(self.filename):
			url,track,chapter = splitDvdUrl(self.filename)
			if track is not None and int(track) > 2:
				track = int(track) - 1
				url = "%s@%d" % (url, track)
			self.playfile(self.servernum, url)
		else:
			path = self.filelist.getPrevFile()
			if path is None:
				self.session.open(MessageBox, _("No previous file in this directory"), MessageBox.TYPE_INFO)
			else:
				servernum, path = path.split(":", 1)
				self.playfile(int(servernum), path)

	def audioTracks(self): 
		return self.session.nav.getCurrentService() and self.session.nav.getCurrentService().audioTracks();

	def seekRelative(self, delta):
		"""delta is seconds as integer number
		positive=forwards, negative=backwards"""
		if self.state != self.STATE_IDLE:
			if (delta >= 0):
				self.vlccontrol.seek("+"+str(delta))
			else:
				self.vlccontrol.seek(str(delta))
		self.vlcservice.refresh()
		if not self.shown:
			self.show()
			self.__setHideTimer()

	def seekFwd(self):
		self.seekRelative(600)

	def seekBack(self):
		self.seekRelative(-600)
