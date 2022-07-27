# simple config reader

class ConfigReader:
    option={}
    def read(self,filename):
        self.option={}
        try:
            fp=open(filename,'r')
            while True:
                s=fp.readline()
                if s:
                    s=s.replace('\r','')
                    s=s.replace('\n','')
                    
                    idx=s.find('=')
                    if idx!=-1:
                        s1=s[:idx]
                        s2=s[idx+1:]
                        self.option[s1]=s2
                else:
                    break
            fp.close()
        except Exception as e:
            print(filename,e)
