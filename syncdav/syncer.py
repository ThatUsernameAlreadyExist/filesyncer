from __future__ import with_statement
from filesystems import LocalFileSystem, WebDavFileSystem, StoredFileSystem
from common import PathOperations, AtomicInteger, DummyLock
import datetime, shutil, sys, random, string, threading
import time
try:
    from concurrent.futures import ThreadPoolExecutor
except ImportError as e:
    print "*** For multithread sync its recommended to install futures: 'pip install futures' ***"


class Syncer:
    STORED_FS_DATA_DIR_NAME = "state"
    BACKUP_DATA_DIR_NAME    = "backup"
    WAIT_ANIMATION_CHARS    = "|/-\\"

    def __init__(self, remoteFs, localFs, logFilePath, settingsDirPath, maxFileSizeKb = 0, maxWorkers=4):
        self.processedDirsCount = AtomicInteger(0)
        self.processedFilesCount = AtomicInteger(0)
        self.updatedDirsCount = AtomicInteger(0)
        self.updatedFilesCount = AtomicInteger(0)
        self.lastFileStatPrintTime = time.time()
        self.fileStatPrintAnimCounter = 0
        self._remoteFs = remoteFs
        self._localFs = localFs
        self._internalFs = LocalFileSystem()
        self.logFilePath = logFilePath
        self.settingsDirPath = settingsDirPath
        self.backupDirPath = self._internalFs.buildPath(self.settingsDirPath, Syncer.BACKUP_DATA_DIR_NAME)
        self.lastSyncPathErrorCount = AtomicInteger(0);
        if not self._internalFs.isExist(self.backupDirPath):
            self._internalFs.createDir(self.backupDirPath)
        self.syncElements = {}
        self.maxFileSizeBytes = maxFileSizeKb * 1024
        if self.maxFileSizeBytes == 0:
            self.maxFileSizeBytes = sys.maxint

        try:
            self.executor = ThreadPoolExecutor(max_workers=maxWorkers)
            self.maxWorkers = maxWorkers
        except Exception, error:
            self.maxWorkers = 1

        if self.maxWorkers > 1:
            self._lock = threading.Lock()
        else:
            self._lock = DummyLock()

        self.activeWorkers = set()


    def addSyncElement(self, remotePath, localPath):
        self.syncElements[remotePath] = localPath


    def sync(self, onlyIfRemoteExist=False, onlyIfLocalExist=False):
        for remotePath, localPath in self.syncElements.iteritems():
            storedLocalFsState = StoredFileSystem(remotePath, localPath, self._internalFs.buildPath(self.settingsDirPath, Syncer.STORED_FS_DATA_DIR_NAME), self.maxWorkers > 1)
            try:
                self._syncPath(remotePath, localPath, storedLocalFsState, onlyIfRemoteExist, onlyIfLocalExist)

                if self.maxWorkers > 1:
                    while self._getBusyWorkersCount() != 0:
                        time.sleep(0.5)

                if self.lastSyncPathErrorCount.get() == 0:
                    self._removeNonExistingDataFromStoredFs(storedLocalFsState, self._localFs)
            except Exception, error:
                self._writeLog("Error: can't sync '" + remotePath.encode('utf8') + "' and '" + localPath.encode('utf8') + "'", error)

        self._printSyncStat(True)
        print ""


    def _syncPath(self, remotePath, localPath, storedLocalFsState, onlyIfRemoteExist, onlyIfLocalExist):
        isRemoteExist = self._remoteFs.isExist(remotePath)
        isLocalExist  = self._localFs.isExist(localPath)
        self.lastSyncPathErrorCount.set(0);

        if isRemoteExist and isLocalExist:
            remoteFileElement = self._remoteFs.getFileSystemElement(remotePath)
            localFileElement = self._localFs.getFileSystemElement(localPath)
            isRemoteFile = not remoteFileElement.isDir
            isLocalFile  = not localFileElement.isDir

            if isRemoteFile != isLocalFile:
                self._writeLog("Sync " + remotePath.encode('utf8') + " to " + localPath.encode('utf8') + " - can't sync file and folder")
            elif isRemoteFile:
                self._syncFile(remotePath, localPath, remoteFileElement, localFileElement, storedLocalFsState, self._remoteFs, self._localFs)
            else: #dir
                self._syncDir(remotePath, localPath, storedLocalFsState, self._remoteFs, self._localFs)

        elif isRemoteExist == onlyIfRemoteExist and isLocalExist == onlyIfLocalExist:
            self._initialSync(remotePath, localPath, isRemoteExist, isLocalExist, storedLocalFsState)
        else:
            self._writeLog("Sync ignored: root folder not exist. " + remotePath + " : " + str(isRemoteExist) + ". " + localPath + " : " + str(isLocalExist))


    def _syncFile(self, remotePath, localPath, remoteFileElement, localFileElement, storedLocalFsState, remoteFs, localFs):
        self.processedFilesCount.inc()

        try:
            storedFileElement = storedLocalFsState.getFileSystemElement(localPath)

            if remoteFileElement != None and localFileElement != None:
                needUpdateLocalElement = remoteFileElement.lastModifiedTimeGMT > localFileElement.lastModifiedTimeGMT and \
                    storedFileElement != None and remoteFileElement.lastModifiedTimeGMT > storedFileElement.lastModifiedTimeGMT

                needUpdateRemoteElement = (not needUpdateLocalElement) and localFileElement.lastModifiedTimeGMT > remoteFileElement.lastModifiedTimeGMT and \
                    (storedFileElement != None) and localFileElement.lastModifiedTimeGMT > storedFileElement.lastModifiedTimeGMT

                if needUpdateLocalElement:
                    if remoteFileElement.size > self.maxFileSizeBytes:
                        self._writeLog("Sync file(ignored local, big remote size - " + str(remoteFileElement.size / 1024) + " KB): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")
                    elif not localFs.isReadOnly():
                        self.updatedFilesCount.inc()
                        content = remoteFs.readFile(remotePath)
                        self._writeBackupFile(localPath)
                        localFs.writeFile(localPath, content)
                        storedLocalFsState.writeFile(localPath, content)
                        self._writeLog("Sync file(write local): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")
                elif needUpdateRemoteElement:
                    if localFileElement.size > self.maxFileSizeBytes:
                        self._writeLog("Sync file(ignored remote, big local size - " + str(localFileElement.size / 1024) + " KB): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
                    elif not remoteFs.isReadOnly():
                        self.updatedFilesCount.inc()
                        content = localFs.readFile(localPath)
                        remoteFs.writeFile(remotePath, content)
                        storedLocalFsState.writeFile(localPath, content)
                        self._writeLog("Sync file(write remote): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")

            elif remoteFileElement != None: # and no local element
                if storedFileElement != None:
                    if not remoteFs.isReadOnly():
                        self.updatedFilesCount.inc()
                        remoteFs.deleteFile(remotePath)
                        self._writeLog("Sync file(delete remote): '" + remotePath.encode('utf8') + "'")
                    storedLocalFsState.deleteFile(localPath)
                elif remoteFileElement.size > self.maxFileSizeBytes:
                    self._writeLog("Sync file(ignored create local, big remote size - " + str(remoteFileElement.size / 1024) + " KB): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")
                elif not localFs.isReadOnly():
                    self.updatedFilesCount.inc()
                    content = remoteFs.readFile(remotePath)
                    self._writeBackupFile(localPath)
                    localFs.writeFile(localPath, content)
                    storedLocalFsState.writeFile(localPath, content)
                    self._writeLog("Sync file(create local): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")

            elif localFileElement != None: # and no remote element
                if storedFileElement != None:
                    if not localFs.isReadOnly():
                        self.updatedFilesCount.inc()
                        self._writeBackupFile(localPath)
                        localFs.deleteFile(localPath)
                        self._writeLog("Sync file(delete local): '" + localPath.encode('utf8') + "'")
                    storedLocalFsState.deleteFile(localPath)
                elif localFileElement.size > self.maxFileSizeBytes:
                     self._writeLog("Sync file(ignored create remote, big local size - " + str(localFileElement.size / 1024) + " KB): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
                elif not remoteFs.isReadOnly():
                    self.updatedFilesCount.inc()
                    content = localFs.readFile(localPath)
                    remoteFs.writeFile(remotePath, content)
                    storedLocalFsState.writeFile(localPath, content)
                    self._writeLog("Sync file(create remote): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
        except Exception, error:
            self.lastSyncPathErrorCount.inc()
            self._writeLog("Error: sync file: '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'", error)

        self._printSyncStat()


    def _removeDoneWorker(self, future):
        with self._lock:
            self.activeWorkers.remove(future)


    def _addBusyWorker(self, future):
        with self._lock:
            self.activeWorkers.add(future)


    def _getBusyWorkersCount(self):
        with self._lock:
            return len(self.activeWorkers)


    def _syncDir(self, remotePath, localPath, storedLocalFsState, remoteFs, localFs, isRemoteExist = True, isLocalExist = True):
        if self.maxWorkers > 1:
            while self._getBusyWorkersCount() >= self.maxWorkers:
                time.sleep(0.3)

            future = self.executor.submit(self._syncDirInternal, remotePath, localPath, storedLocalFsState, remoteFs.clone(), localFs.clone(), isRemoteExist, isLocalExist)
            self._addBusyWorker(future)
            future.add_done_callback(self._removeDoneWorker)
        else:
            self._syncDirInternal(remotePath, localPath, storedLocalFsState, remoteFs, localFs, isRemoteExist, isLocalExist)


    def _syncDirInternal(self, remotePath, localPath, storedLocalFsState, remoteFs, localFs, isRemoteExist = True, isLocalExist = True):
        self.processedDirsCount.inc()

        try:
            needSync = True;
            if not isRemoteExist and not isLocalExist:
                self._writeLog("Error: sync not existing folders: " + remotePath.encode('utf8') + " to " + localPath.encode('utf8'))
                needSync = False
            elif not isRemoteExist:
                if storedLocalFsState.isExist(localPath) and not storedLocalFsState.isFile(localPath):
                    if not localFs.isReadOnly():
                        self.updatedDirsCount.inc()
                        self._writeBackupDir(localPath)
                        localFs.deleteDir(localPath)
                        self._writeLog("Sync dir (delete local): '" + localPath.encode('utf8') + "'")
                    storedLocalFsState.deleteDir(localPath)
                    needSync = False
                elif not remoteFs.isReadOnly():
                    self.updatedDirsCount.inc()
                    remoteFs.createDir(remotePath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (create remote): '" + remotePath.encode('utf8') + "'")
                else:
                    needSync = False
            elif not isLocalExist:
                if storedLocalFsState.isExist(localPath) and not storedLocalFsState.isFile(localPath):
                    if not remoteFs.isReadOnly():
                        self.updatedDirsCount.inc()
                        remoteFs.deleteDir(remotePath)
                        self._writeLog("Sync dir (delete remote): '" + remotePath.encode('utf8') + "'")
                    storedLocalFsState.deleteDir(localPath)
                    needSync = False
                elif not localFs.isReadOnly():
                    self.updatedDirsCount.inc()
                    localFs.createDir(localPath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (create local): '" + localPath.encode('utf8') + "'")
                else:
                    needSync = False

            if needSync:
                remoteElements = self._listDir(remoteFs, remotePath)
                localElements = self._listDir(localFs, localPath)
                localElements = self._syncTwoElementsLists(remotePath, localPath, remoteElements, localElements, True, storedLocalFsState, remoteFs, localFs)
                self._syncTwoElementsLists(remotePath, localPath, remoteElements, localElements, False, storedLocalFsState,  remoteFs, localFs)
        except Exception, error:
            self.lastSyncPathErrorCount.inc()
            self._writeLog("Error: sync dir: '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'", error)

        self._printSyncStat()


    def _syncTwoElementsLists(self, remotePath, localPath, remoteElements, localElements, iterateOnRemoteElements, storedLocalFsState, remoteFs, localFs):
        if iterateOnRemoteElements:
            rElements = remoteElements
            lElements = localElements
            rFs = remoteFs
            lFs = localFs
            rPath = remotePath
            lPath = localPath
        else:
            rElements = localElements
            lElements = remoteElements
            rFs = localFs
            lFs = remoteFs
            rPath = localPath
            lPath = remotePath

        for name, rElement in rElements.iteritems():
            rElementPath = rFs.buildPath(rPath, name)
            lElementPath = lFs.buildPath(lPath, name)
            lElement = None
            needSyncFile = False
            needSyncDir = False

            if name in lElements:
                lElement = lElements[name]
                if rElement.isDir and lElement.isDir:
                    needSyncDir = True
                elif rElement.isDir == lElement.isDir: #files
                    needSyncFile = True
                else:
                    self._writeLog("Error: sync - can't sync file and folder: '" + rElementPath.encode('utf8') + "' to '" + lElementPath.encode('utf8') + "'")

                del lElements[name]
            else:
                if rElement.isDir:
                    needSyncDir = True
                else:
                    needSyncFile = True

            if needSyncFile:
                if iterateOnRemoteElements:
                    self._syncFile(rElementPath, lElementPath, rElement, lElement, storedLocalFsState, remoteFs, localFs)
                else:
                    self._syncFile(lElementPath, rElementPath, lElement, rElement, storedLocalFsState, remoteFs, localFs)
            elif needSyncDir:
                if iterateOnRemoteElements:
                    self._syncDir(rElementPath, lElementPath, storedLocalFsState, remoteFs, localFs, True, lElement != None)
                else:
                    self._syncDir(lElementPath, rElementPath, storedLocalFsState, remoteFs, localFs, lElement != None, True)

        return lElements


    def _listDir(self, fileSystem, path):
        elementsDict = {}
        elements = fileSystem.list(path)
        for element in elements:
            elementsDict[element.name] = element
        return elementsDict


    def _initialSync(self, remotePath, localPath, isRemoteExist, isLocalExist, storedLocalFsState):
        firstFs = None
        secondFs = None
        if isRemoteExist and not isLocalExist:
            firstFs    = self._remoteFs
            firstPath  = remotePath
            secondFs   = self._localFs
            secondPath = localPath;
        elif isLocalExist and not isRemoteExist:
            firstFs    = self._localFs
            firstPath  = localPath
            secondFs   = self._remoteFs
            secondPath = remotePath;
        else:
            self._localFs.createDir(localPath)
            storedLocalFsState.createDir(localPath)
            self._remoteFs.createDir(remotePath)
            self._writeLog("Sync dir (create local and remote): '" + localPath.encode('utf8') + "' and '" + remotePath.encode('utf8') + "'")

        if firstFs != None and secondFs != None:
            if firstFs.isFile(firstPath):
                self.updatedFilesCount.inc()
                fileContent = firstFs.readFile(firstPath)
                secondFs.writeFile(secondPath, fileContent)
                storedLocalFsState.writeFile(localPath, fileContent)
                self._writeLog("Sync file(initial sync): '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'")
            else:
                if not secondFs.isExist(secondPath):
                    self.updatedDirsCount.inc()
                    secondFs.createDir(secondPath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (initial sync): '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'")
                self._syncDir(remotePath, localPath, storedLocalFsState, self._remoteFs, self._localFs)


    def _writeLog(self, log, exception = None):
        if self.logFilePath != None and self.logFilePath != '':
            with open(self.logFilePath, "a") as logFile:
                with self._lock:
                    logFile.write(log + "\n")
                    if exception != None:
                        logFile.write("Exception: " + str(exception) + "\n")


    def _writeBackupFile(self, backupLocalPath):
        with self._lock:
            backupFileName = u'[' + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S").decode('utf8') + u' ' + self._generateRandomStr() + u'] ' + PathOperations.getPathLastElement(backupLocalPath)
            backupFilePath = self._internalFs.buildPath(self.backupDirPath, backupFileName)
            try:
                if self._internalFs.isExist(backupLocalPath): # Support backup only local files.
                    self._internalFs.writeFile(backupFilePath, self._internalFs.readFile(backupLocalPath))
            except Exception, error:
                self._writeLog("Error: can't backup file: '" + backupLocalPath.encode('utf8') + "' to '" + backupFilePath.encode('utf8') + "'", error)


    def _writeBackupDir(self, backupLocalPath):
        with self._lock:
            backupDirName = u'[' + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S").decode('utf8') + u' ' + self._generateRandomStr() + u'] ' + PathOperations.getPathLastElement(backupLocalPath)
            backupDirPath = self._internalFs.buildPath(self.backupDirPath, backupDirName)
            try:
                if self._internalFs.isExist(backupLocalPath): # Support backup only local dirs.
                    shutil.copytree(backupLocalPath, backupDirPath)
            except Exception, error:
                self._writeLog("Error: can't backup dir: '" + backupLocalPath.encode('utf8') + "' to '" + backupDirPath.encode('utf8') + "'", error)


    def _generateRandomStr(self,  length=4):
        characters = string.ascii_letters + string.digits
        return ''.join(random.choice(characters) for _ in range(length)).decode('utf8')


    def _removeNonExistingDataFromStoredFs(self, storedLocalFsState, localFs):
        for localPath in storedLocalFsState.getAllElements():
            if not localFs.isExist(localPath):
                self._writeLog("Remove info about non-existing record: " + localPath.encode('utf8'))
                if storedLocalFsState.isFile(localPath):
                    storedLocalFsState.deleteFile(localPath)
                else:
                    storedLocalFsState.deleteDir(localPath)


    def _printSyncStat(self, force=False):
        with self._lock:
            ts = time.time()
            if force or (ts - self.lastFileStatPrintTime > 1):
                self.lastFileStatPrintTime = ts
                print Syncer.WAIT_ANIMATION_CHARS[self.fileStatPrintAnimCounter], "    Dirs: ", self.processedDirsCount.get(), " [", self.updatedDirsCount.get(), "] / Files: ", self.processedFilesCount.get(), " [", self.updatedFilesCount.get(), "]                  \r",

                self.fileStatPrintAnimCounter += 1
                if self.fileStatPrintAnimCounter > len(Syncer.WAIT_ANIMATION_CHARS) - 1:
                    self.fileStatPrintAnimCounter = 0
