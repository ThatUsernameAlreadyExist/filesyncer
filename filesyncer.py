from __future__ import with_statement
from syncdav import davfs, filesystems, syncer, ntplib
import binascii
import ConfigParser
import datetime
import codecs
import httplib
import ssl
import socket
import hashlib
import time

try:
    import keyring
except ImportError as e:
    print "*** For passwords security its recommended to install keyring: 'pip install keyring' ***"


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
    def __init__(self, syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath, useLocks, threadsCount):
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
        self.useLocks = useLocks
        self.threadsCount = threadsCount

    def isSet(self):
        return self.syncPaths != None and len(self.syncPaths) > 0


    def isLocal(self):
        return self.server != None and self.server == ""


    def isRemote(self):
        return not self.isLocal()


    def isServerSha256FingerprintSet(self):
        return self.sha256 != None and len(self.sha256) > 0


    def getFileSystem(self):
        filesystem = filesystems.WebDavFileSystem(self.server, self.port, self.proto, self.username, self.password, self.useLocks) if self.isRemote() else filesystems.LocalFileSystem()
        return filesystems.ReadOnlyFileSystem(filesystem) if self.isReadOnly else filesystem


class SyncPair:
    def __init__(self):
        self.remote = SyncElement("", "", 0, "", "", "", 0, False, "", True, True,  1)
        self.local  = SyncElement("", "", 0, "", "", "", 0, False, "", True, True, 1)


    def addSyncElement(self, syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath, useLocks, threadsCount):
        syncElement = SyncElement(syncPaths, server, port, proto, username, password, maxFileSizeKb, isReadOnly, sha256, syncOnlyExistingPath, useLocks, threadsCount)
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
    INI_USE_LOCKS              = "UseLocks"
    INI_MAX_THREADS            = "MaxThreads"
    INI_KEYRING_PASS           = "[****]"
    KEYRING_APP_NAME           = "FyleSyncerAccount:user="
    KEYRING_KEY                = "&-^7aTHR!.?20g83h34n03vM:d@ATs]s#2nAy?tn\')8!9)BPGrq8479N%I2J9(0"
    NTP_SERVERS                = ['0.ru.pool.ntp.org',
                                  '3.ru.pool.ntp.org',
                                  'europe.pool.ntp.org',
                                  '3.uk.pool.ntp.org',
                                  '0.us.pool.ntp.org',
                                  '3.us.pool.ntp.org']

    def sync(self, syncTaskList):
        start = time.time()

        self._beginLogSession()
        syncElements = self._getSyncElements()
        for key, element in sorted(syncElements.iteritems()):
            if not syncTaskList or key in syncTaskList:
                print "Start sync for task '" + key + "'"
                taskStart = time.time()

                if len(element.remote.syncPaths) == len(element.local.syncPaths):
                    if self._verifySslFingerprint(element.remote):
                        filesyncer = syncer.Syncer(element.remote.getFileSystem(), element.local.getFileSystem(),
                                                   FileSyncer.LOG_FILE_NAME, FileSyncer.SETTINGS_DATA_DIR,
                                                   max(element.remote.maxFileSizeKb, element.local.maxFileSizeKb),
                                                   max(element.remote.threadsCount, element.local.threadsCount))

                        for index, remotePath in enumerate(element.remote.syncPaths):
                            filesyncer.addSyncElement(remotePath.decode('utf8'), element.local.syncPaths[index].decode('utf8'))

                        filesyncer.sync(element.remote.syncOnlyExistingPath, element.local.syncOnlyExistingPath)
                else:
                    print "Error: not equal amount of paths to sync."

                taskEnd = time.time()
                print "End sync for task '" + key + "'. Sync time: ", round(taskEnd - taskStart, 2), " seconds"

        end = time.time()
        print "Total sync time: ", round(end - start, 2), " seconds"


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

        self._configCryptPasswords(config)

        for section in config.sections():
            config = self._configDecryptPassword(config, section)

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
                                    sectionItems.get(FileSyncer.INI_ONLY_EXISTING_PATH, "1") == "1",
                                    sectionItems.get(FileSyncer.INI_USE_LOCKS, "0") == "1",
                                    int(sectionItems.get(FileSyncer.INI_MAX_THREADS, "1")))

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

    def _configCryptPasswords(self, config):
        hasNewPasswords = False

        for section in config.sections():
            password = ""

            try:
                password = config.get(section, FileSyncer.INI_PASSWORD)

                if password != "" and password != FileSyncer.INI_KEYRING_PASS:
                    server = config.get(section, FileSyncer.INI_SERVER)
                    login  = config.get(section, FileSyncer.INI_LOGIN)

                    keyRingUser = self._xorCrypt(login + '@' + server, FileSyncer.KEYRING_KEY, True)
                    serviceName = FileSyncer.KEYRING_APP_NAME + keyRingUser
                    try:
                        keyring.delete_password(serviceName, keyRingUser)
                    except:
                        pass

                    keyring.set_password(serviceName, keyRingUser, self._xorCrypt(password, FileSyncer.KEYRING_KEY, True))
                    config.set(section, FileSyncer.INI_PASSWORD, FileSyncer.INI_KEYRING_PASS)
                    hasNewPasswords = True

            except Exception, error:
                if password != "":
                    print "Can't save password in keyring - check settings"
                    with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
                        logFile.write("Warning: can't save password in keyring: " + str(error) + "\n")

        if hasNewPasswords:
            with open(FileSyncer.CONFIG_FILE_NAME, 'w') as configfile:
                config.write(configfile)
                print("Success update config and save new password in keyring")

    def _configDecryptPassword(self, config, section):
        password = ""
        try:
            password = config.get(section, FileSyncer.INI_PASSWORD)

            if password == FileSyncer.INI_KEYRING_PASS:
                server = config.get(section, FileSyncer.INI_SERVER)
                login  = config.get(section, FileSyncer.INI_LOGIN)

                keyRingUser = self._xorCrypt(login + '@' + server, FileSyncer.KEYRING_KEY, True)
                password = self._xorCrypt(keyring.get_password(FileSyncer.KEYRING_APP_NAME + keyRingUser, keyRingUser), FileSyncer.KEYRING_KEY, False)
                config.set(section, FileSyncer.INI_PASSWORD, password)

        except Exception, error:
            if password != "":
                print "Can't load password from keyring - check settings"
                with open(FileSyncer.LOG_FILE_NAME, "a") as logFile:
                    logFile.write("Warning: can't load password from keyring: " + str(error) + "\n")

        return config


    def _xorCrypt(self, data, key, toHex):
        res = ""

        if not toHex:
            data = binascii.unhexlify(data)

        for i in range(len(data)):
            res += chr(ord(data[i]) ^ ord(key[i % len(key)]))

        return binascii.hexlify(res) if toHex else res
