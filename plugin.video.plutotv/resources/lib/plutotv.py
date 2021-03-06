#   Copyright (C) 2020 Lunatixz
#
#
# This file is part of PlutoTV.
#
# PlutoTV is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PlutoTV is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PlutoTV.  If not, see <http://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-
import os, sys, time, _strptime, datetime, re, traceback, uuid
import json, collections, inputstreamhelper, requests

from itertools     import repeat, cycle, chain, zip_longest
from resources.lib import xmltv
from simplecache   import SimpleCache, use_cache
from six.moves     import urllib
from kodi_six      import xbmc, xbmcaddon, xbmcplugin, xbmcgui, xbmcvfs, py2_encode, py2_decode

try:
    from multiprocessing import cpu_count 
    from multiprocessing.pool import ThreadPool 
    ENABLE_POOL = True
    CORES = cpu_count()
except: ENABLE_POOL = False

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3
if PY3: 
    basestring = str
    unicode = str
  
# Plugin Info
ADDON_ID      = 'plugin.video.plutotv'
REAL_SETTINGS = xbmcaddon.Addon(id=ADDON_ID)
ADDON_NAME    = REAL_SETTINGS.getAddonInfo('name')
SETTINGS_LOC  = REAL_SETTINGS.getAddonInfo('profile')
ADDON_PATH    = REAL_SETTINGS.getAddonInfo('path')
ADDON_VERSION = REAL_SETTINGS.getAddonInfo('version')
ICON          = REAL_SETTINGS.getAddonInfo('icon')
FANART        = REAL_SETTINGS.getAddonInfo('fanart')
LANGUAGE      = REAL_SETTINGS.getLocalizedString
MONITOR       = xbmc.Monitor()

## GLOBALS ##
LOGO          = os.path.join('special://home/addons/%s/'%(ADDON_ID),'resources','images','logo.png')
LANG          = 'en' #todo
TIMEOUT       = 30
CONTENT_TYPE  = 'episodes'
DISC_CACHE    = False
MY_MONITOR    = xbmc.Monitor()
DTFORMAT      = '%Y%m%d%H%M%S'
PVR_CLIENT    = 'pvr.iptvsimple'
DEBUG         = REAL_SETTINGS.getSettingBool('Enable_Debugging')
USER_PATH     = REAL_SETTINGS.getSetting('User_Folder')
DIRECT_URL    = REAL_SETTINGS.getSettingBool('Direct_URL')
ENABLE_CONFIG = REAL_SETTINGS.getSettingBool('Enable_Config')
USE_COLOR     = REAL_SETTINGS.getSettingBool('Use_Color_Logos')
M3U_FILE      = os.path.join(USER_PATH,'plutotv.m3u')
XMLTV_FILE    = os.path.join(USER_PATH,'plutotv.xml')
GUIDE_URL     = 'https://service-channels.clusters.pluto.tv/v1/guide?start=%s&stop=%s&%s'
BASE_API      = 'https://api.pluto.tv'
BASE_LINEUP   = BASE_API + '/v2/channels.json?%s'
BASE_GUIDE    = BASE_API + '/v2/channels?start=%s&stop=%s&%s'
LOGIN_URL     = BASE_API + '/v1/auth/local?deviceType=web&%s'
BASE_CLIPS    = BASE_API + '/v2/episodes/%s/clips.json'
BASE_VOD      = BASE_API + '/v3/vod/categories?includeItems=true&deviceType=web&%s'
SEASON_VOD    = BASE_API + '/v3/vod/series/%s/seasons?includeItems=true&deviceType=web&%s'

PLUTO_MENU    = [(LANGUAGE(30011), '', 0),
                 (LANGUAGE(30040), '', 0),
                 (LANGUAGE(30018), '', 1),
                 (LANGUAGE(30017), '', 2),
                 (LANGUAGE(30012), '', 3)]
                
INPUTSTREAM       = 'inputstream.adaptive'
INPUTSTREAM_BETA  = 'inputstream.adaptive.testing'
xmltv.locale      = 'UTF-8'
xmltv.date_format = DTFORMAT

def getInputStream():
    if xbmc.getCondVisibility('System.AddonIsEnabled(%s)'%(INPUTSTREAM_BETA)):
        return INPUTSTREAM_BETA
    else: 
        return INPUTSTREAM

def getPTVL():
    return xbmcgui.Window(10000).getProperty('PseudoTVRunning') == 'True'

def hasPTVL():
    return bool(xbmc.getCondVisibility('System.AddonIsEnabled(plugin.video.pseudotv.live)'))

def setUUID():
    if REAL_SETTINGS.getSetting("sid1_hex") and REAL_SETTINGS.getSetting("deviceId1_hex"): return
    REAL_SETTINGS.setSetting("sid1_hex",str(uuid.uuid1().hex))
    REAL_SETTINGS.setSetting("deviceId1_hex",str(uuid.uuid4().hex))

def getUUID():
    return REAL_SETTINGS.getSetting("sid1_hex"), REAL_SETTINGS.getSetting("deviceId1_hex")

def notificationDialog(message, header=ADDON_NAME, show=True, sound=False, time=1000, icon=ICON):
    try:    xbmcgui.Dialog().notification(header, message, icon, time, sound=False)
    except: xbmc.executebuiltin("Notification(%s, %s, %d, %s)" % (header, message, time, icon))

def ProgressBGDialog(percent=0, control=None, message='', header=ADDON_NAME):
    if percent == 0 and control is None:
        control = xbmcgui.DialogProgressBG()
        control.create(header, message)
    elif control:
        if percent == 100 or control.isFinished(): return control.close()
        else: control.update(percent, header, message)
    return control
     
def notificationProgress(message, header=ADDON_NAME, time=4):
    dia = ProgressBGDialog(message=message,header=header)
    for i in range(time):
        if MY_MONITOR.waitForAbort(1): break
        dia = ProgressBGDialog((((i + 1) * 100)//time),control=dia,header=header)
    return ProgressBGDialog(100,control=dia)
    
def strpTime(datestring, format='%Y-%m-%dT%H:%M:%S.%fZ'):
    try: return datetime.datetime.strptime(datestring, format)
    except TypeError: return datetime.datetime.fromtimestamp(time.mktime(time.strptime(datestring, format)))

def timezone():
    if time.localtime(time.time()).tm_isdst and time.daylight: return time.altzone / -(60*60) * 100
    else: return time.timezone / -(60*60) * 100
    
def getLocalTime():
    offset = (datetime.datetime.utcnow() - datetime.datetime.now())
    return time.time() + offset.total_seconds()
        
def log(msg, level=xbmc.LOGDEBUG):
    try:   msg = str(msg)
    except Exception as e: 'log str failed! %s'%(str(e))
    if not DEBUG and level != xbmc.LOGERROR: return
    try:   xbmc.log('%s-%s-%s'%(ADDON_ID,ADDON_VERSION,msg),level)
    except Exception as e: 'log failed! %s'%(e)
     
def slugify(text):
    non_url_safe = [' ','"', '#', '$', '%', '&', '+',',', '/', ':', ';', '=', '?','@', '[', '\\', ']', '^', '`','{', '|', '}', '~', "'"]
    non_url_safe_regex = re.compile(r'[{}]'.format(''.join(re.escape(x) for x in non_url_safe)))
    text = non_url_safe_regex.sub('', text).strip()
    text = u'_'.join(re.split(r'\s+', text))
    return text

def getFavorites():
    return json.loads((REAL_SETTINGS.getSetting('favorites') or '{"favorites":[]}')).get('favorites',[])
     
def isFavorite(chnumber):
    return chnumber in getFavorites()
     
def addFavorite(chname, chnumber, silent=False):
    favorites = getFavorites()
    if chnumber not in favorites:
        favorites.append(chnumber)
        REAL_SETTINGS.setSetting('favorites',json.dumps({"favorites":favorites}))
        if not silent: notificationDialog(LANGUAGE(30036)%(chname))
    
def delFavorite(chname, chnumber):
    favorites = getFavorites()
    if chnumber in favorites:
        favorites.pop(favorites.index(chnumber))
        REAL_SETTINGS.setSetting('favorites',json.dumps({"favorites":favorites}))
        notificationDialog(LANGUAGE(30037)%(chname))
     
class Service(object):
    def __init__(self, sysARG=sys.argv):
        self.running   = False
        self.myMonitor = MONITOR
        self.myPlutoTV = PlutoTV(sysARG)
        

    def regPseudoTV(self):
        log('Service, regPseudoTV')
        name = ADDON_NAME
        if REAL_SETTINGS.getSettingBool('Build_Favorites'): name = '%s (Favorites)'%(name)
        asset = {'type':'iptv','name':name,'path':ADDON_PATH,'icon':ICON.replace(ADDON_PATH,'special://home/addons/%s/'%(ADDON_ID)).replace('\\','/'),'m3u':M3U_FILE,'xmltv':{'path':XMLTV_FILE},'id':ADDON_ID}
        xbmcgui.Window(10000).setProperty('PseudoTV_Recommended.%s'%(ADDON_ID), json.dumps(asset))


    def run(self):
        log('Service, run')
        self.regPseudoTV()
        while not self.myMonitor.abortRequested():
            if self.myMonitor.waitForAbort(5): break
            if not REAL_SETTINGS.getSettingBool('Enable_M3UXMLTV') or self.running: continue
            lastCheck  = float(REAL_SETTINGS.getSetting('Last_Scan') or 0)
            conditions = [xbmcvfs.exists(M3U_FILE),xbmcvfs.exists(XMLTV_FILE)]
            if (time.time() > (lastCheck + 3600)) or (False in conditions):
                self.running = True
                if hasPTVL():
                    REAL_SETTINGS.setSetting('Enable_Config','false')
                if self.myPlutoTV.buildService():
                    self.regPseudoTV()
                    REAL_SETTINGS.setSetting('Last_Scan',str(time.time()))
                    notificationProgress(LANGUAGE(30031)%(ADDON_NAME))
                self.running = False
                

class PlutoTV(object):
    def __init__(self, sysARG=sys.argv):
        log('__init__, sysARG = %s'%(sysARG))
        setUUID()
        self.myMonitor = MONITOR
        self.sysARG    = sysARG
        self.cache     = SimpleCache()
        self.m3uList   = []
        self.xmltvList = {'data'       : self.getData(),
                          'channels'   : [],
                          'programmes' : []}
                          
            
    def reset(self):
        self.__init__()
        
            
    def getURL(self, url, param={}, header={'User-agent': 'Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0'}, life=datetime.timedelta(minutes=15)):
        log('getURL, url = %s, header = %s'%(url, header))
        cacheresponse = self.cache.get('%s.getURL, url = %s.%s.%s'%(ADDON_NAME,url,param,header))
        if not cacheresponse:
            try:
                req = requests.get(url, param, headers=header)
                cacheresponse = req.json()
                req.close()
            except Exception as e: 
                log("getURL, Failed! %s"%(e), xbmc.LOGERROR)
                notificationDialog(LANGUAGE(30001))
                return {}
            try:
                self.cache.set('%s.getURL, url = %s.%s.%s'%(ADDON_NAME,url,param,header), json.dumps(cacheresponse), expiration=life)
            except: pass
            return cacheresponse
        else: 
            return json.loads(cacheresponse)

      
    def buildHeader(self):
        header_dict               = {}
        header_dict['Accept']     = 'application/json, text/javascript, */*; q=0.01'
        header_dict['Host']       = 'api.pluto.tv'
        header_dict['Connection'] = 'keep-alive'
        header_dict['Referer']    = 'http://pluto.tv/'
        header_dict['Origin']     = 'http://pluto.tv'
        header_dict['User-Agent'] = 'Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0'
        return header_dict


    def mainMenu(self):
        log('mainMenu')
        for item in PLUTO_MENU: self.addDir(*item)


    def getOndemand(self):
        return self.getURL(BASE_VOD%(LANGUAGE(30022)%(getUUID())), header=self.buildHeader(), life=datetime.timedelta(hours=1))


    def getVOD(self, epid):
        return self.getURL(SEASON_VOD%(epid,LANGUAGE(30022)%(getUUID())), header=self.buildHeader(), life=datetime.timedelta(hours=1))
        
        
    def getClips(self, epid):
        return self.getURL(BASE_CLIPS%(epid), header=self.buildHeader(), life=datetime.timedelta(hours=1))
        
        
    def getChannels(self):
        return sorted(self.getURL(BASE_LINEUP%(LANGUAGE(30022)%(getUUID())), header=self.buildHeader(), life=datetime.timedelta(hours=1)), key=lambda i: i['number'])
        

    def getGuidedata(self, full=False):
        start = (datetime.datetime.fromtimestamp(getLocalTime()).strftime('%Y-%m-%dT%H:00:00Z'))
        stop  = (datetime.datetime.fromtimestamp(getLocalTime()) + datetime.timedelta(hours=4)).strftime('%Y-%m-%dT%H:00:00Z')
        if full: return self.getURL(GUIDE_URL %(start,stop,LANGUAGE(30022)%(getUUID())), life=datetime.timedelta(hours=1))
        else: return sorted((self.getURL(BASE_GUIDE %(start,stop,LANGUAGE(30022)%(getUUID())), life=datetime.timedelta(hours=1))), key=lambda i: i['number'])

        
    def getCategories(self):
        log('getCategories')
        
        # categories = sorted(self.getGuidedata(full=True).get('categories',[]), key=lambda k: k['order'])
        # for category in categories: 
            # yield (category['name'], 'categories', 0, False, {'thumb':category.get('images',[{}])[0].get('url',ICON),'fanart':category.get('images',[{},{}])[1].get('url',FANART)})
        
        collect= []
        data = self.getChannels()
        for channel in data: collect.append(channel['category'])
        counter = collections.Counter(collect)
        categories = sorted(self.getGuidedata(full=True).get('categories',[]), key=lambda k: k['order'])
        for key, value in sorted(counter.items()): 
            category = {}
            for category in categories:
                if category['name'].lower() == key.lower():
                    break
            yield (key,'categories', 0, False, {'thumb':category.get('images',[{}])[0].get('url',ICON),'fanart':category.get('images',[{},{}])[1].get('url',FANART)})
        
        
    def buildGuide(self, data):
        channel, name, opt = data
        log('buildGuide, name=%s,opt=%s'%(name, opt))
        urls      = []
        guidedata = []
        newChannel= {}
        mtype     = 'video'
        chid      = channel.get('_id','')
        chname    = channel.get('name','')
        chnum     = channel.get('number','')
        chplot    = (channel.get('description','') or channel.get('summary',''))
        chgeo     = channel.get('visibility','everyone') != 'everyone'
        chcat     = (channel.get('category','')    or channel.get('genre',''))
        chfanart  = channel.get('featuredImage',{}).get('path',FANART)
        chthumb   = channel.get('thumbnail',{}).get('path',ICON)
        
        chlogo    = channel.get('logo',{}).get('path',ICON) 
        if USE_COLOR:
            chlogo = channel.get('colorLogoPNG',{}).get('path',chlogo)

        ondemand  = channel.get('onDemand','false') == 'true'
        featured  = channel.get('featured','false') == 'true'
        timelines = channel.get('timelines',[])
        
        favorite  = channel.get('favorite','false') == 'true'
        if favorite: 
            addFavorite(chnum, silent=True)
        
        if name.startswith('live'):
            favorite = isFavorite(chnum)
            if '(favorites)' in name and not favorite: 
                return None
        else:
            favorite = None
        if   name == 'featured'   and not featured: return None
        elif name == 'favorite'   and not favorite: return None
        elif name == 'categories' and chcat != opt: return None
        elif name == 'lineup'     and chid  != opt: return None
        elif name.startswith('live'): DISC_CACHE = False
            
        if name in ['channels','categories','ondemand','season']:
            if name == 'season':
                seasons   = (channel.get('seasons',{}))
                vodimages = channel.get('covers',[])
                try:    vodlogo   = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '1:1'][0]
                except: vodlogo   = ''
                try:    vodfanart = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '16:9'][0]
                except: vodfanart = ''
                
                for season in seasons:
                    vodlogo   = (vodlogo   or chlogo)
                    vodfanart = (vodfanart or FANART)
                    mtype = 'episode'
                    label = 'Season %s'%(season['number'])
                    infoLabels = {"mediatype":mtype,"label":label,"label2":label,"title":chname,"plot":chplot, "code":chid, "genre":[chcat]}
                    infoArt    = {"thumb":vodlogo,"poster":vodlogo,"fanart":vodfanart,"icon":vodlogo,"logo":vodlogo,"clearart":chthumb}
                    self.addDir(label, chid, 5, infoLabels, infoArt)
            else:
                if name == 'ondemand': 
                    mode  = 3
                    label = chname
                else:  
                    mode  = 1
                    label = '%s| %s'%(chnum,chname)
                infoLabels = {"mediatype":mtype,"label":label,"label2":label,"title":label,"plot":chplot, "code":chid, "genre":[chcat]}
                infoArt    = {"thumb":chthumb,"poster":chthumb,"fanart":chfanart,"icon":chlogo,"logo":chlogo,"clearart":chthumb}
                self.addDir(label, chid, mode, infoLabels, infoArt)
        else:
            newChannel['channelname']   = chname
            newChannel['channelnumber'] = chnum
            newChannel['channellogo']   = chlogo
            newChannel['isfavorite']    = favorite
            urls = channel.get('stitched',{}).get('urls',[])
            if not timelines:
                name = 'ondemand'
                timelines = (channel.get('items',[]) or channel.get('episodes',[]))
                
            now = datetime.datetime.now()
            totstart = now
            tz = (timezone()//100)*60*60
            
            for item in timelines:
                episode    = (item.get('episode',{})   or item)
                series     = (episode.get('series',{}) or item)
                epdur      = int(episode.get('duration','0') or '0') // 1000
                urls       = (item.get('stitched',{}).get('urls',[]) or urls)
                if len(urls) == 0: continue
                if isinstance(urls, list): urls  = [url['url'] for url in urls if url['type'].lower() == 'hls'][0] # todo select quality
                
                try:
                    start  = strpTime(item['start'],'%Y-%m-%dT%H:%M:00.000Z') + datetime.timedelta(seconds=tz)
                    stop   = strpTime(item['stop'],'%Y-%m-%dT%H:%M:00.000Z')  + datetime.timedelta(seconds=tz)
                except:
                    start  = totstart
                    stop   = start + datetime.timedelta(seconds=epdur)
                totstart   = stop  
                
                type       = series.get('type','')
                tvtitle    = series.get('name',''                           or chname)
                title      = (item.get('title',''))
                tvplot     = (series.get('description','')                  or series.get('summary','')      or chplot)
                tvoutline  = (series.get('summary','')                      or series.get('description','')  or chplot)
                tvthumb    = (series.get('featuredImage',{}).get('path','') or chfanart)
                tvfanart   = (series.get('featuredImage',{}).get('path','') or chfanart)
                epid       = episode['_id']
                epnumber   = episode.get('number',0)
                epseason   = episode.get('season',0)
                epname     = (episode['name'])
                epplot     = (episode.get('description','') or tvplot or epname)
                epgenre    = (episode.get('genre','')       or chcat)
                eptag      = episode.get('subGenre','')
                epmpaa     = episode.get('rating','')
                epislive   = episode.get('liveBroadcast','false') == 'true'
                vodimages  = episode.get('covers',[])
                vodposter  = vodfanart = vodthumb = vodlogo = ''
                
                if vodimages:
                    try:    vodposter = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '347:500'][0]
                    except: pass
                    try:    vodfanart = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '16:9'][0]
                    except: pass
                    try:    vodthumb  = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '4:3'][0]
                    except: pass
                    try:    vodlogo   = [image.get('url',[]) for image in vodimages if image.get('aspectRatio','') == '1:1'][0]
                    except: pass

                chlogo     = (vodlogo or chlogo)
                epposter   = (episode.get('poster',{}).get('path','')        or vodlogo   or vodposter or vodthumb  or tvthumb)
                epthumb    = (episode.get('thumbnail',{}).get('path','')     or vodlogo   or vodthumb  or vodposter or tvthumb)
                epfanart   = (episode.get('featuredImage',{}).get('path','') or vodfanart or tvfanart)
                
                label      = title
                thumb      = chthumb
                if type in ['movie','film']:
                    mtype  = 'movie'
                    thumb  = epposter
                elif type in ['tv','episode','series']:
                    mtype  = 'episode'
                    thumb  = epposter
                    if epseason > 0 and epnumber > 0:
                        label  = '%sx%s'%(epseason, epnumber)
                        label  = '%s - %s'%(label, epname)
                        # else: label  = '%s - %s'%(tvtitle, label)
                    else: label = epname
                    epname = label
                    if type == 'music' or epgenre.lower() == 'music': mtype = 'musicvideo'

                if name.startswith('live'):
                    if stop < now or start > now: continue
                    # epdur = (now - start).seconds
                    label = '%s| %s'%(chnum,chname)
                    if type in ['movie','film']:
                        mtype = 'movie'
                        thumb = epposter
                        label = '%s : [B]%s[/B]'%(label, title)
                    elif type in ['tv','series']:
                        mtype = 'episode'
                        thumb = epposter
                        label = "%s : [B]%s - %s[/B]" % (label, tvtitle, epname)
                    elif len(epname) > 0: label = '%s: [B]%s - %s[/B]'%(label, title, epname)
                    epname = label
                    if type == 'music' or epgenre.lower() == 'music': mtype = 'musicvideo'

                elif name == 'lineup':
                    if now > stop: continue
                    # elif start >= now and stop < now: epdur = (now - start).seconds
                    if type in ['movie','film']:
                        mtype = 'movie'
                        thumb = epposter
                        label = '%s'%(title)
                    elif type in ['tv','series']:
                        mtype = 'episode'
                        thumb = epposter
                        label = "%s - %s" % (tvtitle, epname)
                    elif len(epname) > 0: label = '%s - %s'%(title, epname)
                    epname = label
                    if type == 'music' or epgenre.lower() == 'music': mtype = 'musicvideo'
                    if now >= start and now < stop: 
                        label = '%s - [B]%s[/B]'%(start.strftime('%I:%M %p').lstrip('0'),label)
                    else: 
                        label = '%s - %s'%(start.strftime('%I:%M %p').lstrip('0'),label)
                        urls  = 'NEXT_SHOW'
                    epname = label

                tmpdata = {"mediatype":mtype,"label":label,"title":label,'duration':epdur,'plot':epplot,'genre':[epgenre],'season':epseason,'episode':epnumber}
                tmpdata['starttime'] = time.mktime((start).timetuple())
                tmpdata['url'] = self.sysARG[0]+'?mode=9&name=%s&url=%s'%(title,urls)
                tmpdata['art'] = {"thumb":thumb,"poster":epposter,"fanart":epfanart,"icon":chlogo,"logo":chlogo,"clearart":chthumb}
                guidedata.append(tmpdata)
                
                if name == 'ondemand' and type == "series":
                    mtype = 'season'
                    infoLabels = {"mediatype":mtype,"label":label,"label2":label,"title":label,"plot":epplot, "code":chid, "genre":[epgenre]}
                    infoArt    = {"thumb":epthumb,"poster":epposter,"fanart":epfanart,"icon":chlogo,"logo":chlogo,"clearart":chthumb}
                    self.addDir(label, epid, 4, infoLabels, infoArt)
                elif name != 'guide':
                    infoLabels = {"favorite":favorite,"chnum":chnum,"chname":chname,"mediatype":mtype,"label":label,"label2":label,"tvshowtitle":tvtitle,"title":epname,"plot":epplot, "code":epid, "genre":[epgenre], "duration":epdur,'season':epseason,'episode':epnumber}
                    infoArt    = {"thumb":thumb,"poster":epposter,"fanart":epfanart,"icon":chlogo,"logo":chlogo,"clearart":chthumb}
                    self.addLink(title, urls, 9, infoLabels, infoArt)
                    
            CONTENT_TYPE = '%ss'%mtype
            if len(guidedata) > 0:
                newChannel['guidedata'] = guidedata
                return newChannel
        

    def browseGuide(self, name, opt=None, data=None):
        log('browseGuide, name=%s, opt=%s'%(name,opt))
        self.chnums = []
        if data is None: data = self.getGuidedata()
        if opt == 'categories': 
            opt  = name
            name = 'categories'
            data = self.getGuidedata(full=True).get('categories',[])
        self.poolList(self.buildGuide, zip(data,repeat(name.lower()),repeat(opt)))
             
             
    def browseLineup(self, name, opt=None):
        log('browseLineup, opt=%s'%opt)
        if opt is None: name = 'channels'
        else: name = 'lineup'
        self.browseGuide(name, opt)
        
      
    def browseOndemand(self, opt=None):
        log('browseOndemand')
        data = self.getOndemand()['categories']
        if opt is None: name = 'ondemand'
        else: name = 'lineup'
        self.browseGuide(name, opt, data)
        
        
    def browseSeason(self, opt=None):
        log('browseSeason')
        data = [self.getVOD(opt)]
        self.browseGuide('season', opt, data)
        
        
    def browseEpisodes(self, name, opt=None):
        log('browseEpisodes')
        season = int(name.split('Season ')[1])
        data = [self.getVOD(opt).get('seasons',[])[season - 1]]
        self.browseGuide('episode', opt, data)
                
                
    def browseCategories(self):
        log('browseCategories')
        categoryMenu = self.getCategories()
        for item in categoryMenu: self.addDir(*item)
       
       
    def playVOD(self, name, id):
        log('playVOD, id = %s'%id)
        data = self.getClips(id)[0]
        if not data: return
        name  = data.get('name',name)
        epdur = (data.get('duration',0) // 1000)
        url   = (data.get('url','') or data.get('sources',[])[0].get('file',''))
        liz   = xbmcgui.ListItem(name)
        liz.setPath(url)
        liz.setInfo(type="Video", infoLabels={"mediatype":"video","label":name,"title":name,"duration":epdur})
        liz.setArt({'thumb':data.get('thumbnail',ICON),'fanart':data.get('thumbnail',FANART)})
        liz.setProperty("IsPlayable","true")
        if 'm3u8' in url.lower() and inputstreamhelper.Helper('hls').check_inputstream():
            inputstream = getInputStream()
            liz.setProperty('inputstream',inputstream)
            liz.setProperty('%s.manifest_type'%(inputstream),'hls')
            liz.setMimeType('application/vnd.apple.mpegurl')
        xbmcplugin.setResolvedUrl(int(self.sysARG[1]), True, liz)
        
        
    def playVideo(self, name, url, liz=None):
        if url.lower() == 'next_show': 
            found = False
            liz   = xbmcgui.ListItem(name)
            return notificationDialog(LANGUAGE(30029), time=4000)
        else:
            found = True
            if url.endswith('?deviceType='): url = url.replace('deviceType=','deviceType=&deviceMake=&deviceModel=&&deviceVersion=unknown&appVersion=unknown&deviceDNT=0&userId=&advertisingId=&app_name=&appName=&buildVersion=&appStoreUrl=&architecture=&includeExtendedEvents=false')#todo lazy fix replace
            if 'sid' not in url: url = url.replace('deviceModel=&','deviceModel=&' + LANGUAGE(30022)%(getUUID()))
            url = url.replace('deviceType=&','deviceType=web&').replace('deviceMake=&','deviceMake=Chrome&') .replace('deviceModel=&','deviceModel=Chrome&').replace('appName=&','appName=web&')#todo replace with regex!
            log('playVideo, url = %s'%url)
            if liz is None: liz = xbmcgui.ListItem(name, path=url)
            if 'm3u8' in url.lower() and inputstreamhelper.Helper('hls').check_inputstream():
                inputstream = getInputStream()
                liz.setProperty('inputstream',inputstream)
                liz.setProperty('%s.manifest_type'%(inputstream),'hls')
                liz.setMimeType('application/vnd.apple.mpegurl')
        xbmcplugin.setResolvedUrl(int(self.sysARG[1]), found, liz)

           
    def addLink(self, name, u, mode, infoList=False, infoArt=False, total=0):
        log('addLink, name = %s'%name)
        liz=xbmcgui.ListItem(name)
        liz.setProperty('IsPlayable', 'true') 
        
        if infoList.get('favorite',None) is not None:
            if infoList['favorite']:
                liz.addContextMenuItems([(LANGUAGE(30039), 'RunScript(special://home/addons/%s/context.py, %s)'%(ADDON_ID,urllib.parse.quote(json.dumps({"chnum":infoList.pop('chnum'),"chname":infoList.pop('chname'),"mode":"del"}))))])
            else:
                liz.addContextMenuItems([(LANGUAGE(30038), 'RunScript(special://home/addons/%s/context.py, %s)'%(ADDON_ID,urllib.parse.quote(json.dumps({"chnum":infoList.pop('chnum'),"chname":infoList.pop('chname'),"mode":"add"}))))])
            
        if infoList == False: liz.setInfo(type="Video", infoLabels={"mediatype":"video","label":name,"title":name})
        else: liz.setInfo(type="Video", infoLabels=infoList)
        if infoArt == False: liz.setArt({'thumb':ICON,'fanart':FANART})
        else: liz.setArt(infoArt)
        u=self.sysARG[0]+"?url="+urllib.parse.quote(u)+"&mode="+str(mode)+"&name="+urllib.parse.quote(name)
        xbmcplugin.addDirectoryItem(handle=int(self.sysARG[1]),url=u,listitem=liz,totalItems=total)


    def addDir(self, name, u, mode, infoList=False, infoArt=False):
        log('addDir, name = %s'%name)
        liz=xbmcgui.ListItem(name)
        liz.setProperty('IsPlayable', 'false')
        if infoList == False: liz.setInfo(type="Video", infoLabels={"mediatype":"video","label":name,"title":name} )
        else: liz.setInfo(type="Video", infoLabels=infoList)
        if infoArt == False: liz.setArt({'thumb':ICON,'fanart':FANART})
        else: liz.setArt(infoArt)
        u=self.sysARG[0]+"?url="+urllib.parse.quote(u)+"&mode="+str(mode)+"&name="+urllib.parse.quote(name)
        xbmcplugin.addDirectoryItem(handle=int(self.sysARG[1]),url=u,listitem=liz,isFolder=True)


    def getData(self):
        log('getData')
        return {'date'                : datetime.datetime.fromtimestamp(float(time.time())).strftime(xmltv.date_format),
                'generator-info-name' : self.cleanString('%s Guidedata'%(ADDON_NAME)),
                'generator-info-url'  : self.cleanString(ADDON_ID),
                'source-info-name'    : self.cleanString(ADDON_NAME),
                'source-info-url'     : self.cleanString(ADDON_ID)}


    def save(self, reset=True):
        log('save')
        if len(self.m3uList) > 0:
            log('save, saving m3u to %s'%(M3U_FILE))
            fle = xbmcvfs.File(M3U_FILE, 'w')
            if not self.m3uList[0].startswith('#EXTM3U'):
                self.m3uList.insert(0,'#EXTM3U tvg-shift="" x-tvg-url="" x-tvg-id=""')
            fle.write('\n'.join([item for item in self.m3uList]))
            fle.close()
        
        data   = self.xmltvList['data']
        writer = xmltv.Writer(encoding=xmltv.locale, date=data['date'],
                              source_info_url     = data['source-info-url'], 
                              source_info_name    = data['source-info-name'],
                              generator_info_url  = data['generator-info-url'], 
                              generator_info_name = data['generator-info-name'])
               
        channels = self.sortChannels(self.xmltvList['channels'])
        if len(channels) > 0:
            for channel in channels: writer.addChannel(channel)
            programmes = self.sortProgrammes(self.xmltvList['programmes'])
            for program in programmes: writer.addProgramme(program)
            log('save, saving xmltv to %s'%(XMLTV_FILE))
            writer.write(XMLTV_FILE, pretty_print=True)
        return True
        
        
    def sortChannels(self, channels=None):
        channels.sort(key=lambda x:x['id'])
        log('sortChannels, channels = %s'%(len(channels)))
        return channels


    def sortProgrammes(self, programmes=None):
        programmes.sort(key=lambda x:x['channel'])
        programmes.sort(key=lambda x:x['start'])
        log('sortProgrammes, programmes = %s'%(len(programmes)))
        return programmes


    def buildService(self):
        log('buildService')
        self.reset()
        channels = self.getChannels()
        [self.buildM3U(channel) for channel in channels]
        guidedata = self.getGuidedata(full=True).get('channels',[])
        # if self.poolList(self.buildXMLTV, guidedata):
        for data in guidedata:
            self.buildXMLTV(data)
        self.save()
        self.chkSettings()
        return True
        
        
    def getPVR(self):
        try: return xbmcaddon.Addon(PVR_CLIENT)
        except: # backend disabled?
            self.togglePVR('true')
            xbmc.sleep(1000)
            try:
                return xbmcaddon.Addon(PVR_CLIENT)
            except: return None
            
            
    def chkSettings(self):
        if ENABLE_CONFIG:
            addon = self.getPVR()
            if addon is None: return
            check = [addon.getSetting('catchupEnabled')         == 'true',
                     addon.getSetting('m3uRefreshMode')         == '1',
                     addon.getSetting('m3uRefreshIntervalMins') == '5',
                     addon.getSetting('logoFromEpg')            == '1',
                     addon.getSetting('m3uPathType')            == '0',
                     addon.getSetting('m3uPath')                == M3U_FILE,
                     addon.getSetting('epgPathType')            == '0',
                     addon.getSetting('epgPath')                == XMLTV_FILE]
            if False in check: self.configurePVR()
        
        
    def configurePVR(self):
        addon = self.getPVR()
        addon.setSetting('catchupEnabled'        , 'true')
        addon.setSetting('m3uRefreshMode'        , '1')
        addon.setSetting('m3uRefreshIntervalMins', '5')
        addon.setSetting('logoFromEpg'           , '1')
        addon.setSetting('m3uPathType'           , '0')
        addon.setSetting('m3uPath'               , M3U_FILE)
        addon.setSetting('epgPathType'           , '0')
        addon.setSetting('epgPath'               , XMLTV_FILE)
        
        
    def buildM3U(self, channel):
        litem = '#EXTINF:-1 tvg-chno="%s" tvg-id="%s" tvg-name="%s" tvg-logo="%s" group-title="%s" radio="%s"%s,%s\n%s'
        favorite = isFavorite(channel['number'])
        logo  = (channel.get('logo',{}).get('path',LOGO) or LOGO)
        
        group = [channel.get('category','')]
        group.append('Pluto TV')
        if favorite:
            group.append('Favorite')
            
        radio   = False #True if "Music" in group else False
        catchup = True #todo look for ondemand key that works!
        if radio or not catchup: 
            vod = ''
        else:
            vod = ' catchup="vod"'
            
        urls  = channel.get('stitched',{}).get('urls',[])
        if len(urls) == 0: 
            return False
        elif REAL_SETTINGS.getSettingBool('Build_Favorites') and not favorite: 
            return False
            
        if isinstance(urls, list): urls = [url['url'] for url in urls if url['type'].lower() == 'hls'][0] # todo select quality
        if DIRECT_URL:
            url  = '#KODIPROP:inputstream={inputstream}\n#KODIPROP:{inputstream}.manifest_type=hls\n#KODIPROP:mimetype=application/vnd.apple.mpegurl\n%s'.format(inputstream=getInputStream())
            urls = url%(urls)
        else:
            urls = 'plugin://%s/?mode=9&name=%s&url=%s'%(ADDON_ID,urllib.parse.quote(self.cleanString(channel['name'])),urllib.parse.quote(urls))
            
        self.m3uList.append(litem%(channel['number'],'%s@%s'%(channel['number'],slugify(ADDON_NAME)),channel['name'],logo,';'.join(list(set(group))),str(radio).lower(),vod,channel['name'],urls))
        return True
        
        
    def buildXMLTV(self, channel):
        self.addChannel(channel)
        for program in  channel.get('timelines',[]): 
            self.addProgram(channel, program)
        return True
        
        
    def addChannel(self, channel):
        logo  = [logo.get('url',ICON) for logo in channel.get('images',[]) if logo.get('type','') == 'logo'][0]
        citem = ({'id'           : '%s@%s'%(channel['number'],slugify(ADDON_NAME)),
                  'display-name' : [(self.cleanString(channel['name']), LANG)],
                  'icon'         : [{'src':logo}]})
        log('addChannel = %s'%(citem))
        self.xmltvList['channels'].append(citem)
        return True


    def addProgram(self, channel, program):
        episode = program.get('episode',{})
        series  = episode.get('series',{})
        uri     = episode.get('_id','')
        pitem   = {'channel'     : '%s@%s'%(channel['number'],slugify(ADDON_NAME)),
                   'category'    : [(self.cleanString(episode.get('genre','Undefined')),LANG)],
                   'title'       : [(self.cleanString(program['title']), LANG)],
                   'desc'        : [((self.cleanString(episode.get('description','')) or xbmc.getLocalizedString(161)), LANG)],
                   'stop'        : (strpTime(program['stop'] ,'%Y-%m-%dT%H:%M:%S.%fZ')).strftime(xmltv.date_format),
                   'start'       : (strpTime(program['start'],'%Y-%m-%dT%H:%M:%S.%fZ')).strftime(xmltv.date_format),
                   'icon'        : [{'src': (episode.get('poster','') or episode.get('thumbnail','') or episode.get('featuredImage',{})).get('path',FANART)}]}
                   
        if int(episode.get('duration','0') or '0') > 0:
            pitem['length']    = {'units': 'seconds', 'length': str(int(episode['duration']) // 1000)}
    
        if uri:
            pitem['catchup-id'] = 'plugin://%s/?mode=8&name=%s&url=%s'%(ADDON_ID,urllib.parse.quote(self.cleanString(program['title'])),urllib.parse.quote(uri))

        if episode.get('name',''):
            pitem['sub-title'] = [(self.cleanString(episode['name']), LANG)]
            
        if episode.get('clip',{}).get('originalReleaseDate',''):
            try:
                pitem['date'] = (strpTime(episode['clip']['originalReleaseDate'])).strftime('%Y%m%d')
            except: pass

        if episode.get('rating',''):
            rating = program.get('rating','')
            if rating.startswith('TV'): 
                pitem['rating'] = [{'system': 'VCHIP', 'value': rating}]
            else:  
                pitem['rating'] = [{'system': 'MPAA', 'value': rating}]
      
        log('addProgram = %s'%(pitem))
        self.xmltvList['programmes'].append(pitem)
        return True
     
     
    def cleanString(self, text):
        if text is None: return ''
        return re.sub(u'[^\n\r\t\x20-\x7f]+',u'',text)
        
        
    def poolList(self, method, items=None, args=None, chunk=25):
        log("poolList")
        results = []
        if ENABLE_POOL:
            pool = ThreadPool(CORES)
            if args is not None: 
                results = pool.map(method, zip(items,repeat(args)))
            elif items: 
                results = pool.map(method, items)#, chunksize=chunk)
            pool.close()
            pool.join()
        else:
            if args is not None: 
                results = [method((item, args)) for item in items]
            elif items: 
                results = [method(item) for item in items]
        return filter(None, results)

        
    def getParams(self):
        return dict(urllib.parse.parse_qsl(self.sysARG[2][1:]))

            
    def run(self):    
        params=self.getParams()
        try: url=urllib.parse.unquote_plus(params["url"])
        except: url=None
        try: name=urllib.parse.unquote_plus(params["name"])
        except: name=None
        try: mode=int(params["mode"])
        except: mode=None
        log("Mode: "+str(mode))
        log("URL : "+str(url))
        log("Name: "+str(name))

        if mode==None:
            if getPTVL(): 
                return notificationDialog(LANGUAGE(30042))
            self.mainMenu()
        elif mode == 0 :  self.browseGuide(name, url)
        elif mode == 1 :  self.browseLineup(name, url)
        elif mode == 2 :  self.browseCategories()
        elif mode == 3 :  self.browseOndemand(url)
        elif mode == 4 :  self.browseSeason(url)
        elif mode == 5 :  self.browseEpisodes(name, url)
        elif mode == 8 :  self.playVOD(name, url)
        elif mode == 9 :  self.playVideo(name, url)
        
        xbmcplugin.setContent(int(self.sysARG[1])    , CONTENT_TYPE)
        xbmcplugin.addSortMethod(int(self.sysARG[1]) , xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(int(self.sysARG[1]) , xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.addSortMethod(int(self.sysARG[1]) , xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.addSortMethod(int(self.sysARG[1]) , xbmcplugin.SORT_METHOD_TITLE)
        xbmcplugin.endOfDirectory(int(self.sysARG[1]), cacheToDisc=DISC_CACHE)