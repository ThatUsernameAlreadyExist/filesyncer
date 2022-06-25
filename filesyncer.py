from __future__ import with_statement
from syncdav import davfs, filesystems, syncer, ntplib
import ConfigParser
import datetime
import codecs
import httplib
import ssl
import socket
import hashlib
import time


def _disableCertificateCheck(server):
    try:
        _create_unverified_https_context = ssl._create_unverified_context
    except AttributeError:
        # Legacy Python that doesn't verify HTTPS certificates by default
        pass
    else:
        # Handle target environment that doesn't support HTTPS verification
        ssl._create_default_https_context = _create_unverified_https_context
        with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
            logFile.write(server + ": server SSL Certificate check DISABLED. Server SHA256 fingerprint check ENABLED.\n")


def _enableCertificateCheck(server):
    try:
        _create_verified_https_context = ssl.create_default_context
    except AttributeError:
        # Legacy Python that doesn't verify HTTPS certificates by default
        pass
    else:
        # Handle target environment that doesn't support HTTPS verification
        ssl._create_default_https_context = _create_verified_https_context
        with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
            logFile.write(server + ": server SSL Certificate check ENABLED. Server SHA256 fingerprint check DISABLED.\n")


class SyncElement:
    def __init__(self, syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath):
        self.syncPaths = syncPaths
        self.server = server
        self.port = port
        self.proto = proto
        self.username = username
        self.password = password
        self.maxFileSizeKb = maxFileSizeKb
        self.isReadOnly = isReadOnly
        self.sha256 = sha256
        self.syncOnlyExistingPath = syncOnlyExistingPath

    def isSet(self):
        return self.syncPaths != None and len(self.syncPaths) > 0


    def isLocal(self):
        return self.server != None and self.server == ""


    def isRemote(self):
        return not self.isLocal()


    def isServerSha256FingerprintSet(self):
        return self.sha256 != None and len(self.sha256) > 0


    def getFileSystem(self):
        filesystem = filesystems.WebDavFileSystem(self.server, self.port, self.proto, self.username, self.password) if self.isRemote() else filesystems.LocalFileSystem()
        return filesystems.ReadOnlyFileSystem(filesystem) if self.isReadOnly else filesystem


class SyncPair:
    def __init__(self):
        self.remote = SyncElement("", "", 0, "", "", "", 0, False, "", False)
        self.local  = SyncElement("", "", 0, "", "", "", 0, False, "", False)


    def addSyncElement(self, syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath):
        syncElement = SyncElement(syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath)
        if syncElement.isRemote() and not self.remote.isSet():
            self.remote = syncElement
        elif syncElement.isLocal() and not self.local.isSet():
            self.local = syncElement
        elif not self.remote.isSet():
            self.remote = syncElement
        else:
            self.local = syncElement


class FileSyncer:
    CONFIG_FILE_NAME           = "FileSyncer.ini"
    LOG_FILE_NAME              = "FileSyncer.log"
    LOG_START_MARKER           = "--------------"
    SETTINGS_DATA_DIR          = "FileSyncerData"
    BACKUP_DATA_DIR            = "FileSyncerBackup"
    INI_SYNC_PATHS             = "SyncPaths"
    INI_SYNC_PATH_DELIMITER    = "|"
    INI_SECTION_NAME_DELIMITER = " "
    INI_LOGIN                  = "Username"
    INI_PASSWORD               = "Password"
    INI_SERVER                 = "Server"
    INI_SERVER_PORT            = "Port"
    INI_SERVER_PROTO           = "Proto"
    INI_MAX_FILE_SIZE_KB       = "MaxFileSizeKB"
    INI_READ_ONLY_FLAG         = "ReadOnly"
    INI_SERVER_SHA256          = "ServerSha256"
    INI_ONLY_EXISTING_PATH     = "OnlyIfSyncPathExist"
    NTP_SERVERS                = ['0.ru.pool.ntp.org',
                                  '3.ru.pool.ntp.org',
                                  'europe.pool.ntp.org',
                                  '3.uk.pool.ntp.org',
                                  '0.us.pool.ntp.org',
                                  '3.us.pool.ntp.org']

    def sync(self):
        start = time.time()

        self._beginLogSession()
        syncElements = self._getSyncElements()
        for key, element in syncElements.iteritems():
            print "Start sync for task '" + key + "'"
            taskStart = time.time()

            if len(element.remote.syncPaths) == len(element.local.syncPaths):
                if self._verifySslFingerprint(element.remote):
                    filesyncer = syncer.Syncer(element.remote.getFileSystem(), element.local.getFileSystem(),
                                               FileSyncer.LOG_FILE_NAME, FileSyncer.SETTINGS_DATA_DIR,
                                               max(element.remote.maxFileSizeKb, element.local.maxFileSizeKb))

                    for index, remotePath in enumerate(element.remote.syncPaths):
                        filesyncer.addSyncElement(remotePath.decode('utf8'), element.local.syncPaths[index].decode('utf8'))

                    filesyncer.sync(element.remote.syncOnlyExistingPath, element.local.syncOnlyExistingPath)
            else:
                print "Error: not equal amount of paths to sync."

            taskEnd = time.time()
            print "End sync for task '" + key + "'. Sync time: ", round(taskEnd - taskStart, 2), " seconds"

        end = time.time()
        print "Total sync time: ", round(taskEnd - taskStart, 2), " seconds"


    def getLastSyncLogLines(self):
        lastLog = []
        with codecs.open(FileSyncer.LOG_FILE_NAME, "r", "utf8") as f:
            for line in f:
                if line.startswith(FileSyncer.LOG_START_MARKER):
                    lastLog = []
                else:
                    lastLog.append(line)
        return lastLog


    def _getSyncElements(self):
        syncElements = {}
        config = ConfigParser.ConfigParser()
        config.optionxform = str # Disable lowercase config keys transform.
        config.read(FileSyncer.CONFIG_FILE_NAME)
        for section in config.sections():
            syncElementName = self._getSyncElementName(section)
            syncPair = syncElements.get(syncElementName, SyncPair())
            sectionItems = {}
            for key, val in config.items(section):
                sectionItems[key] = val

            syncPair.addSyncElement(sectionItems.get(FileSyncer.INI_SYNC_PATHS, "").split(FileSyncer.INI_SYNC_PATH_DELIMITER),
                                    sectionItems.get(FileSyncer.INI_SERVER, ""),
                                    int(sectionItems.get(FileSyncer.INI_SERVER_PORT, "0")),
                                    sectionItems.get(FileSyncer.INI_SERVER_PROTO, "https"),
                                    sectionItems.get(FileSyncer.INI_LOGIN, ""),
                                    sectionItems.get(FileSyncer.INI_PASSWORD, ""),
                                    int(sectionItems.get(FileSyncer.INI_MAX_FILE_SIZE_KB, "0")),
                                    sectionItems.get(FileSyncer.INI_READ_ONLY_FLAG, "0") == "1",
                                    sectionItems.get(FileSyncer.INI_SERVER_SHA256, ""),
                                    sectionItems.get(FileSyncer.INI_ONLY_EXISTING_PATH, "1") == "1")

            syncElements[syncElementName] = syncPair

        return syncElements


    def _getSyncElementName(self, section):
        return section.split(FileSyncer.INI_SECTION_NAME_DELIMITER)[0]


    def _getHttpTime(self):
        conn = httplib.HTTPConnection("just-the-time.appspot.com")
        conn.request("GET", "/")
        resp = conn.getresponse()
        data = resp.read()
        return datetime.datetime.strptime(data.strip(), '%Y-%m-%d %H:%M:%S')


    def _beginLogSession(self):
        with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
            logFile.write(FileSyncer.LOG_START_MARKER + "\n" + str(datetime.datetime.now()) + ":\n\n")
            netSecondsOffset = 0
            isNetTimeObtained = False

            try:
                netTime = self._getHttpTime()
                isNetTimeObtained = True
                td = datetime.datetime.utcnow() - netTime
                netSecondsOffset = (td.microseconds + (td.seconds + td.days * 24 * 3600) * 10**6) / 10**6
            except:
                print "Get NTP time..."
                ntpClient = ntplib.NTPClient()
                initialTimeout = 5
                for server in FileSyncer.NTP_SERVERS:
                    try:
                        response = ntpClient.request(server, version=3, timeout=initialTimeout)
                        isNetTimeObtained = True
                        netSecondsOffset = response.offset
                        break
                    except:
                        if initialTimeout > 1:
                            initialTimeout = initialTimeout - 1

            if not isNetTimeObtained:
                logFile.write("Error: can't get internet time.\n")
            elif abs(netSecondsOffset) > 60:
                logFile.write("Warning: system time out of sync. May occur synchronization errors and data loss.\n")


    def _verifySslFingerprint(self, syncElement):
        response = True

        if syncElement.isServerSha256FingerprintSet():
            _disableCertificateCheck(syncElement.server)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            wrappedSocket = ssl.wrap_socket(sock)
            realFingerprint = ""

            try:
                wrappedSocket.connect((syncElement.server, syncElement.port))
            except Exception, error:
                #print error
                response = False
            else:
                der_cert_bin = wrappedSocket.getpeercert(True)
                thumb_sha256 = hashlib.sha256(der_cert_bin).hexdigest()

                if thumb_sha256 == None or thumb_sha256 != syncElement.sha256:
                    response = False
                    realFingerprint = thumb_sha256

            wrappedSocket.close()

            if not response:
                with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
                    logFile.write("Error: Can't verify server fingerprint: " + syncElement.server +  "[" + realFingerprint + "]\n")
        else:
            _enableCertificateCheck(syncElement.server)

        return response