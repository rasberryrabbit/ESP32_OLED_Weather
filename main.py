""" main. py """

from machine import Timer, Pin, I2C, SoftI2C, RTC
import micropython, re, time, network, socket, ntptime, configreader, sh1106, random, framebuf
micropython.alloc_emergency_exception_buf(100)
import vga1_8x8 as font1

class ConfigError(RuntimeError):
    pass

def epochtotime(ept, offset):
    return time.gmtime(ept-946684800+offset)

def fileexists(fn):
    try:
        f=open(fn,'r')
        f.close()
        return True
    except:
        return False

# display
i2c=SoftI2C(scl=Pin(4),sda=Pin(5))
disp=sh1106.SH1106_I2C(128,64,i2c,None,0x3c,rotate=180)
disp.fill(0)
disp.show()
disp.contrast(0x5f)

# read config       
config=configreader.ConfigReader()
if fileexists('config.txt'):
    config.read('config.txt')
else:
    print('config.txt is missing. Writing sample.')
    f=open('config.txt','w')
    f.write('ssid=\n')
    f.write('pass=\n')
    f.write('lat=\n')
    f.write('lon=\n')
    f.write('appid=\n')
    f.close()
    raise ConfigError
    
ssid=config.option['ssid']
passw=config.option['pass']
lat=config.option['lat']
lon=config.option['lon']
appid=config.option['appid']
if appid=='':
    print('Missing info in config.txt.')
    raise ConfigError
#print(config.option)

delaych=['/','-','\\','|']
# wifi connection
ignlist={}
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

def tryconnect(dispid):
    global ssid, passw, ignlist
    wlan.disconnect()
    while wlan.isconnected():
        pass
    if not wlan.isconnected():
      disp.text('Connect',0,0)
      disp.text(ssid,0,8)
      disp.show()
      print('Connect %s' % (ssid))
      wlan.connect(ssid,passw)
      trycounter=0
      while not wlan.isconnected():
          trycounter+=1
          if trycounter>60:
              ignlist[ssid]=1
              # connect to open wifi
              wl=wlan.scan()
              ap_count=0
              for wap in wl:
                  if ignlist[wap[0]]!=1 and wap[4]==0:
                      ap_count+=1
                      ssid=wap[0]
                      passw=''
                      wlan.connect(ssid,passw)
                      trycounter=0
                      disp.text('Connect ',0,0)
                      if dispid:
                          disp.text(ssid,0,8)
                      print('Connect %s' % (ssid))
              # reset ignore list
              if ap_count==0:
                  ignlist={}
                  trycounter=0
                  time.sleep(30)
                  ssid=config.option['ssid']
                  passw=config.option['pass']
                  wlan.connect(ssid,passw)
                  disp.text('ReConnect ',0,0)
                  if dispid:
                      disp.text(ssid,0,8)
                  print('ReConnect %s' % (ssid))
          disp.fill_rect(120,0,9,8,0)
          disp.text(delaych[trycounter % 4],120,0)
          disp.show()
          time.sleep_ms(500)
    print('network config:',wlan.ifconfig())
    
tryconnect(True)

def synctime():
    counter=0
    while True:
        try:
            ntptime.settime()
            break
        except Exception as e:
            print(e)
            print("sync time")
            disp.fill_rect(120,0,9,8,0)
            disp.text(delaych[counter % 4],120,0)
            disp.show()
            counter+=1
        time.sleep(1)

# ntp time
rtc=RTC()
synctime()
print(time.localtime())

# open weather
class OpenWeather:
    ContLen=-1
    last_remain=b''
    timeoffset=9*3600
    to_send=b''
    imgoffset=0
    firststamp=0
    error_count=0
    weinfo=[]
    
    def __init__(self,lat,lon,appid):
        self.last_remain=b''
        self.to_send=b'GET /data/2.5/onecall?lat=%s&lon=%s&exclude=minutely,daily,alerts&appid=%s&units=metric HTTP/1.1\r\nHost: api.openweathermap.org\r\nConnection: keep-alive\r\nAccept: */*\r\n\r\n' % (lat,lon,appid)
    
    def GetInfo(self):
        while True:
            y=time.localtime(time.time()+self.timeoffset)
            if y[0]>2000:
                break
            disp.text('wait sync',0,0)
            print('wait sync')
            synctime()
            time.sleep_ms(1000)
        try:
            sock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            saddr=socket.getaddrinfo('api.openweathermap.org',80)[0][-1]
            sock.connect(saddr)
            #sock.setblocking(0)
            
            self.last_remain=b''
            self.ContLen=-1
            self.imageoffset=0
            self.firststamp=0
            self.weinfo=[]
            sock.sendall(self.to_send)
            while True:
                data=sock.recv(1024)
                if data:
                   # check header
                   if self.ContLen==-1:
                       i=data.decode().find('\r\n\r\n')
                       if i!=-1:
                           i+=4
                           s=re.search("Content\-Length:\s+(\d+)",data)
                           if s:
                               self.ContLen=int(s.group(1))
                           else:
                               self.ContLen=8192
                           data=data[i:]
                   # process body
                   ilen=len(data)
                   self.ContLen-=ilen
                   if self.ContLen<=0:
                       break
                   data=self.last_remain+data
                   self.last_remain=b''
                   if self.imgoffset>2:
                       data=b''
                       break
                   spos=0
                   epos=0
                   # timezone
                   tzi=re.search("timezone_offset\":(\d+),",data)
                   if tzi:
                       stimezone=tzi.group(1)
                       self.timeoffset=int(stimezone)
                   while True:
                       spos=data.decode().find("{\"dt\":")
                       epos=data.decode().find("}]")
                       if epos!=-1:
                           epos+=2
                       if spos!=-1 and epos!=-1 and epos>spos:
                           sdayw=re.search("dt\":(\d+)",data)
                           if sdayw:
                               dayw=int(sdayw.group(1))
                           else:
                               dayw=0
                           if self.firststamp==0:
                               self.firststamp=dayw
                           stemp=re.search("temp\":([0-9\.]+)",data)
                           if stemp:
                               ttemp=float(stemp.group(1))
                           else:
                               ttemp=0.0
                           swind=re.search("wind_speed\":([0-9\.]+)",data)
                           if swind:
                               windspd=float(swind.group(1))
                           else:
                               windspd=0.0
                           shum=re.search("humidity\":(\d+)",data)
                           if shum:
                               hum=int(shum.group(1))
                           else:
                               hum=0
                           scloud=re.search("clouds\":(\d+)",data)
                           if scloud:
                               cloud=int(scloud.group(1))
                           else:
                               cloud=0
                           spress=re.search("pressure\":(\d+)",data)
                           if spress:
                               press=int(spress.group(1))
                           else:
                               press=0
                           suvi=re.search("uvi\":([0-9\.]+)",data)
                           if suvi:
                               uvi=float(suvi.group(1))
                           else:
                               uvi=0.0
                           sicon=re.search("icon\":\"([^\"]+)\"",data)
                           if sicon:
                               weicon="we_"+sicon.group(1).decode()+".pbm"
                           else:
                               weicon="none.pbm"
                           spop=re.search("pop\":([0-9\.]+)",data)
                           if spop:
                               vpop=float(spop.group(1))
                           else:
                               vpop=0.0
                           srain=re.search("rain\":{\"1h\":([0-9\.]+)",data)
                           if srain is None:
                               srain=re.search("snow\":{\"1h\":([0-9\.]+)",data)                               
                           if srain:
                               rain=float(srain.group(1))
                           else:
                               rain=0.0
                           # info array
                           if self.firststamp<=dayw:
                               self.weinfo.append([dayw,ttemp,windspd,hum,weicon,vpop,cloud,press,uvi,rain])
                               self.imgoffset+=1
                           data=data[epos:]
                           if self.imgoffset>2:
                               break
                       else:
                           self.last_remain=data
                           break
                # no data
                else:
                    break
            sock.close()
        except Exception as e:
            print(e)
            print(" parser")
        if self.imgoffset>2:
            self.error_count=0
            return True
        else:
            self.error_count+=1
            return False

winfo=OpenWeather(lat,lon,appid)
#print(946684800 + time.time() - 9*3600)

def drawvline(x,y,h):
    for yi in range(random.randint(0,1),h,2):
        disp.pixel(x,y+yi,1)

def drawtemp(x,y,t):
    disp.text('T',x,y)
    disp.text('%4.1f' % (t),x+10,y)
    
def drawhumi(x,y,h):
    disp.text('H',x,y)
    disp.text('%3d%%' % (h),x+10,y)
    
def drawpop(x,y,pop):
    xp=int(pop*100)
    disp.text('%3d%%' % (xp),x,y)
    drawvline(x-2,y,8)
    
def drawrain(x,y,rain):
    disp.text('%4.2f' % (rain),x,y)
    drawvline(x-2,y,8)    
    
def drawwind(x,y,wind):
    disp.text('W',x,y)
    disp.text('%4.1f' % (wind),x+10,y)
    
def drawuvi(x,y,uvi):
    disp.text('%4.2f' % (uvi),x,y)
    
def loadpbm(x,y,fname):
    f=open(fname,'rb')
    f.readline()
    f.readline()
    f.readline()
    data=bytearray(f.read())
    f.close()
    for i, v in enumerate(data):
        data[i]=~v
    fimg=framebuf.FrameBuffer(data,32,32,framebuf.MONO_HLSB)
    disp.blit(fimg,x,y)

def displayinfo(bpop):
    i=0
    idx=0
    px=random.randint(0,2)
    disp.fill(0)
    rt=time.localtime(time.time()+winfo.timeoffset)
    disp.text('%2d:%02d' %(rt[3],rt[4]),px+0,0)
    for wi in winfo.weinfo:
        if idx>0:
            dt=epochtotime(wi[0],winfo.timeoffset)
            disp.text('%2dH' % (dt[3]),px+58,i)
            drawtemp(px+0,i+8,wi[1])
            drawhumi(px+0,i+16,wi[3])
            drawwind(px+0,i+24,wi[2])
            disp.text('%3d%%' % (wi[6]),px+50,i+8)
            if bpop:
                if wi[5]>0.0:
                    drawpop(px+50,i+16,wi[5])
                if wi[9]>0.0:
                    drawrain(px+50,i+24,wi[9])
            else:
                if wi[8]>0.0:
                    drawuvi(px+50,i+16,wi[8])
                disp.text('%4d' % (wi[7]),px+50,i+24)
            if fileexists(wi[4]):
                loadpbm(px+90,i,wi[4])
            else:
                print('error',wi[4])
            drawvline(px+45,i+8,24)
            i+=32
        idx+=1
    disp.show()

def displayinfoTHW():
    i=0
    idx=0
    px=random.randint(0,2)
    for wi in winfo.weinfo:
        if idx>0:
            disp.fill_rect(0,i+8,44,24,0)
            dt=epochtotime(wi[0],winfo.timeoffset)
            disp.fill_rect(50,i,41,8,0)
            disp.text('%2dH' % (dt[3]),px+58,i)
            drawtemp(px+0,i+8,wi[1])
            drawhumi(px+0,i+16,wi[3])
            drawwind(px+0,i+24,wi[2])
            i+=32
        idx+=1
    disp.show()    

def displayinfoex(bpop):
    i=0
    idx=0
    px=random.randint(0,2)
    rt=time.localtime(time.time()+winfo.timeoffset)
    disp.fill_rect(0,0,49,8,0)
    disp.text('%2d:%02d' %(rt[3],rt[4]),px+0,0)
    for wi in winfo.weinfo:
        if idx>0:
            disp.fill_rect(48,i+8,43,24,0)
            disp.text('%3d%%' % (wi[6]),px+50,i+8)
            if bpop:
                if wi[5]>0.0:
                    drawpop(px+50,i+16,wi[5])
                if wi[9]>0.0:
                    drawrain(px+50,i+24,wi[9])
            else:
                if wi[8]>0.0:
                    drawuvi(px+50,i+16,wi[8])
                disp.text('%4d' % (wi[7]),px+50,i+24)
            disp.fill_rect(91,i,37,32,0)
            if fileexists(wi[4]):
                loadpbm(px+90,i,wi[4])
            else:
                print('error',wi[4])
            i+=32
        idx+=1
    disp.show()    
    
tmTime=Timer(0)
# update every 5 minutes
tmUpdate = Timer(1)

timeoff=0
showuvi=0

def cbTime(t):
    global timeoff,showuvi
    if showuvi==0:
        displayinfoTHW()
    if showuvi==1 or showuvi==3:
        displayinfoex(showuvi<2)
    showuvi+=1
    showuvi%=4
    # Night mode
    rt=time.localtime(time.time()+winfo.timeoffset)
    if rt[3]>20 or rt[3]<7:
        if timeoff>=5:
            timeoff=0
            disp.contrast(0)
    else:
        if timeoff>=5:
            timeoff=0
            disp.contrast(0x5f)
        elif timeoff==3:
            disp.contrast(0)
    timeoff+=1
       
def cbUpdate(t):
    tmTime.deinit()
    tmUpdate.deinit()
    try:
        winfo.imgoffset=0
        if winfo.GetInfo():
            #print(winfo.weinfo)
            displayinfo(True)
            print('ok')
        else:
            if winfo.error_count>3:
                winfo.error_count=0
                wlan.disconnect()
                tryconnect(True)
    except Exception as e:
        print(e)
        print(" Update")
    tmTime.init(period=1000, mode=Timer.PERIODIC, callback=cbTime)
    tmUpdate.init(period=300000, mode=Timer.PERIODIC, callback=cbUpdate)

        
cbUpdate(0)