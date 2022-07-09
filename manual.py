from __future__ import with_statement
import filesyncer
import time
import platform
from os import system
import sys

#-----------------------------------------------
system("title FileSyncer (p. " + platform.python_version() + ")")
print "Start sync"

fsyncer = filesyncer.FileSyncer()
start = time.time()
fsyncer.sync(sys.argv[1:])
end = time.time()

print "End sync. Time elapsed: " + str(end - start) + " seconds"
print "------------"
print "Result:"
time.sleep(1)

# print last sync log.
errorDetected = False

try:
    for line in fsyncer.getLastSyncLogLines():
        try:
            decodedLine = line.decode('utf8')
            if decodedLine.startswith("Error: "):
                errorDetected = True

            print decodedLine, #print without newline
        except:
            print line,
except Exception, error:
    errorDetected = True
    print error
    pass

if errorDetected:
    print "\n\n!!!-----[ Sync ERROR ]-----!!!"
    print "\a"
    time.sleep(86400)
else:
    print "Waiting 15 seconds..."
    time.sleep(15)