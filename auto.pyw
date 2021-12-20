import filesyncer
import time 
import httplib

fileSyncer = filesyncer.FileSyncer()
while True:
    sleepMinutes = 60
    try:
        conn = httplib.HTTPConnection("www.google.com")
        try:
            conn.request("HEAD", "/")
            print "Internet available"
        except:
            sleepMinutes = 2
            print "Internet not available"
            
        fileSyncer.sync()
        time.sleep(sleepMinutes * 60) # in seconds
    except:
        pass
        