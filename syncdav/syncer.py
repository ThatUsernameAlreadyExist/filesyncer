from __future__ import with_statement
from filesystems import LocalFileSystem, WebDavFileSystem, StoredFileSystem
from common import PathOperations
import datetime, shutil, sys
import time


class Syncer:
    STORED_FS_DATA_DIR_NAME = "state"
    BACKUP_DATA_DIR_NAME    = "backup"
    WAIT_ANIMATION_CHARS    = "|/-\\"

    def __init__(self, remoteFs, localFs, logFilePath, settingsDirPath, maxFileSizeKb = 0):
        self.processedDirsCount = 0
        self.processedFilesCount = 0
        self.updatedDirsCount = 0
        self.updatedFilesCount = 0
        self.lastFileStatPrintTime = time.time()
        self.fileStatPrintAnimCounter = 0
        self.remoteFs = remoteFs
        self.localFs = localFs
        self.logFilePath = logFilePath
        self.settingsDirPath = settingsDirPath
        self.backupDirPath = self.localFs.buildPath(self.settingsDirPath, Syncer.BACKUP_DATA_DIR_NAME)
        self.lastSyncPathErrorCount = 0;
        if not self.localFs.isExist(self.backupDirPath):
            self.localFs.createDir(self.backupDirPath)
        self.syncElements = {}
        self.maxFileSizeBytes = maxFileSizeKb * 1024
        if self.maxFileSizeBytes == 0:
            self.maxFileSizeBytes = sys.maxint


    def addSyncElement(self, remotePath, localPath):
        self.syncElements[remotePath] = localPath


    def sync(self, onlyIfRemoteExist=False, onlyIfLocalExist=False):
        for remotePath, localPath in self.syncElements.iteritems():
            storedLocalFsState = StoredFileSystem(remotePath, localPath, self.localFs.buildPath(self.settingsDirPath, Syncer.STORED_FS_DATA_DIR_NAME))
            try:
                self._syncPath(remotePath, localPath, storedLocalFsState, onlyIfRemoteExist, onlyIfLocalExist)
                if self.lastSyncPathErrorCount == 0:
                    self._removeNonExistingDataFromStoredFs(storedLocalFsState, self.localFs)
            except Exception, error:
                self._writeLog("Error: can't sync '" + remotePath.encode('utf8') + "' and '" + localPath.encode('utf8') + "'", error)

        self._printSyncStat(True)
        print ""

    def _syncPath(self, remotePath, localPath, storedLocalFsState, onlyIfRemoteExist, onlyIfLocalExist):
        isRemoteExist = self.remoteFs.isExist(remotePath)
        isLocalExist  = self.localFs.isExist(localPath)
        self.lastSyncPathErrorCount = 0;

        if isRemoteExist and isLocalExist:
            remoteFileElement = self.remoteFs.getFileSystemElement(remotePath)
            localFileElement = self.localFs.getFileSystemElement(localPath)
            isRemoteFile = not remoteFileElement.isDir
            isLocalFile  = not localFileElement.isDir

            if isRemoteFile != isLocalFile:
                self._writeLog("Sync " + remotePath.encode('utf8') + " to " + localPath.encode('utf8') + " - can't sync file and folder")
            elif isRemoteFile:
                self._syncFile(remotePath, localPath, remoteFileElement, localFileElement, storedLocalFsState)
            else: #dir
                self._syncDir(remotePath, localPath, storedLocalFsState)

        elif isRemoteExist == onlyIfRemoteExist and isLocalExist == onlyIfLocalExist:
            self._initialSync(remotePath, localPath, isRemoteExist, isLocalExist, storedLocalFsState)
        else:
            self._writeLog("Sync ignored: root folder not exist. " + remotePath + " : " + str(isRemoteExist) + ". " + localPath + " : " + str(isLocalExist))


    def _syncFile(self, remotePath, localPath, remoteFileElement, localFileElement, storedLocalFsState):
        self.processedFilesCount += 1

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
                    elif not self.localFs.isReadOnly():
                        self.updatedFilesCount += 1
                        content = self.remoteFs.readFile(remotePath)
                        self._writeBackupFile(localPath)
                        self.localFs.writeFile(localPath, content)
                        storedLocalFsState.writeFile(localPath, content)
                        self._writeLog("Sync file(write local): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")
                elif needUpdateRemoteElement:
                    if localFileElement.size > self.maxFileSizeBytes:
                        self._writeLog("Sync file(ignored remote, big local size - " + str(localFileElement.size / 1024) + " KB): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
                    elif not self.remoteFs.isReadOnly():
                        self.updatedFilesCount += 1
                        content = self.localFs.readFile(localPath)
                        self.remoteFs.writeFile(remotePath, content)
                        storedLocalFsState.writeFile(localPath, content)
                        self._writeLog("Sync file(write remote): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")

            elif remoteFileElement != None: # and no local element
                if storedFileElement != None:
                    if not self.remoteFs.isReadOnly():
                        self.updatedFilesCount += 1
                        self.remoteFs.deleteFile(remotePath)
                        self._writeLog("Sync file(delete remote): '" + remotePath.encode('utf8') + "'")
                    storedLocalFsState.deleteFile(localPath)
                elif remoteFileElement.size > self.maxFileSizeBytes:
                    self._writeLog("Sync file(ignored create local, big remote size - " + str(remoteFileElement.size / 1024) + " KB): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")
                elif not self.localFs.isReadOnly():
                    self.updatedFilesCount += 1
                    content = self.remoteFs.readFile(remotePath)
                    self._writeBackupFile(localPath)
                    self.localFs.writeFile(localPath, content)
                    storedLocalFsState.writeFile(localPath, content)
                    self._writeLog("Sync file(create local): '" + remotePath.encode('utf8') + "' -> '" + localPath.encode('utf8') + "'")

            elif localFileElement != None: # and no remote element
                if storedFileElement != None:
                    if not self.localFs.isReadOnly():
                        self.updatedFilesCount += 1
                        self._writeBackupFile(localPath)
                        self.localFs.deleteFile(localPath)
                        self._writeLog("Sync file(delete local): '" + localPath.encode('utf8') + "'")
                    storedLocalFsState.deleteFile(localPath)
                elif localFileElement.size > self.maxFileSizeBytes:
                     self._writeLog("Sync file(ignored create remote, big local size - " + str(localFileElement.size / 1024) + " KB): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
                elif not self.remoteFs.isReadOnly():
                    self.updatedFilesCount += 1
                    content = self.localFs.readFile(localPath)
                    self.remoteFs.writeFile(remotePath, content)
                    storedLocalFsState.writeFile(localPath, content)
                    self._writeLog("Sync file(create remote): '" + localPath.encode('utf8') + "' -> '" + remotePath.encode('utf8') + "'")
        except Exception, error:
            self.lastSyncPathErrorCount += 1
            self._writeLog("Error: sync file: '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'", error)

        self._printSyncStat()


    def _syncDir(self, remotePath, localPath, storedLocalFsState, isRemoteExist = True, isLocalExist = True):
        self.processedDirsCount += 1

        try:
            needSync = True;
            if not isRemoteExist and not isLocalExist:
                self._writeLog("Error: sync not existing folders: " + remotePath.encode('utf8') + " to " + localPath.encode('utf8'))
                needSync = False
            elif not isRemoteExist:
                if storedLocalFsState.isExist(localPath) and not storedLocalFsState.isFile(localPath):
                    if not self.localFs.isReadOnly():
                        self.updatedDirsCount += 1
                        self._writeBackupDir(localPath)
                        self.localFs.deleteDir(localPath)
                        self._writeLog("Sync dir (delete local): '" + localPath.encode('utf8') + "'")
                    storedLocalFsState.deleteDir(localPath)
                    needSync = False
                elif not self.remoteFs.isReadOnly():
                    self.updatedDirsCount += 1
                    self.remoteFs.createDir(remotePath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (create remote): '" + remotePath.encode('utf8') + "'")
                else:
                    needSync = False
            elif not isLocalExist:
                if storedLocalFsState.isExist(localPath) and not storedLocalFsState.isFile(localPath):
                    if not self.remoteFs.isReadOnly():
                        self.updatedDirsCount += 1
                        self.remoteFs.deleteDir(remotePath)
                        self._writeLog("Sync dir (delete remote): '" + remotePath.encode('utf8') + "'")
                    storedLocalFsState.deleteDir(localPath)
                    needSync = False
                elif not self.localFs.isReadOnly():
                    self.updatedDirsCount += 1
                    self.localFs.createDir(localPath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (create local): '" + localPath.encode('utf8') + "'")
                else:
                    needSync = False

            if needSync:
                remoteElements = self._listDir(self.remoteFs, remotePath)
                localElements = self._listDir(self.localFs, localPath)
                localElements = self._syncTwoElementsLists(remotePath, localPath, remoteElements, localElements, True, storedLocalFsState)
                self._syncTwoElementsLists(remotePath, localPath, remoteElements, localElements, False, storedLocalFsState)
        except Exception, error:
            self.lastSyncPathErrorCount += 1
            self._writeLog("Error: sync dir: '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'", error)

        self._printSyncStat()


    def _syncTwoElementsLists(self, remotePath, localPath, remoteElements, localElements, iterateOnRemoteElements, storedLocalFsState):
        if iterateOnRemoteElements:
            rElements = remoteElements
            lElements = localElements
            rFs = self.remoteFs
            lFs = self.localFs
            rPath = remotePath
            lPath = localPath
        else:
            rElements = localElements
            lElements = remoteElements
            rFs = self.localFs
            lFs = self.remoteFs
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
                    self._syncFile(rElementPath, lElementPath, rElement, lElement, storedLocalFsState)
                else:
                    self._syncFile(lElementPath, rElementPath, lElement, rElement, storedLocalFsState)
            elif needSyncDir:
                if iterateOnRemoteElements:
                    self._syncDir(rElementPath, lElementPath, storedLocalFsState, True, lElement != None)
                else:
                    self._syncDir(lElementPath, rElementPath, storedLocalFsState, lElement != None, True)

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
            firstFs    = self.remoteFs
            firstPath  = remotePath
            secondFs   = self.localFs
            secondPath = localPath;
        elif isLocalExist and not isRemoteExist:
            firstFs    = self.localFs
            firstPath  = localPath
            secondFs   = self.remoteFs
            secondPath = remotePath;
        else:
            self.localFs.createDir(localPath)
            storedLocalFsState.createDir(localPath)
            self.remoteFs.createDir(remotePath)
            self._writeLog("Sync dir (create local and remote): '" + localPath.encode('utf8') + "' and '" + remotePath.encode('utf8') + "'")

        if firstFs != None and secondFs != None:
            if firstFs.isFile(firstPath):
                self.updatedFilesCount += 1
                fileContent = firstFs.readFile(firstPath)
                secondFs.writeFile(secondPath, fileContent)
                storedLocalFsState.writeFile(localPath, fileContent)
                self._writeLog("Sync file(initial sync): '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'")
            else:
                if not secondFs.isExist(secondPath):
                    self.updatedDirsCount += 1
                    secondFs.createDir(secondPath)
                    storedLocalFsState.createDir(localPath)
                    self._writeLog("Sync dir (initial sync): '" + localPath.encode('utf8') + "' <-> '" + remotePath.encode('utf8') + "'")
                self._syncDir(remotePath, localPath, storedLocalFsState)


    def _writeLog(self, log, exception = None):
        if self.logFilePath != None and self.logFilePath != '':
            with open(self.logFilePath, "a") as logFile:
                logFile.write(log + "\n")
                if exception != None:
                    logFile.write("Exception: " + str(exception) + "\n")


    def _writeBackupFile(self, backupLocalPath):
        backupFileName = u'[' + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S").decode('utf8') + u']' + PathOperations.getPathLastElement(backupLocalPath)
        backupFilePath = self.localFs.buildPath(self.backupDirPath, backupFileName)
        try:
            if self.localFs.isExist(backupLocalPath):
                self.localFs.writeFile(backupFilePath, self.localFs.readFile(backupLocalPath))
        except Exception, error:
            self._writeLog("Error: can't backup file: '" + backupLocalPath.encode('utf8') + "' to '" + backupFilePath.encode('utf8') + "'", error)


    def _writeBackupDir(self, backupLocalPath):
        backupDirName = u'[' + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S").decode('utf8') + u']' + PathOperations.getPathLastElement(backupLocalPath)
        backupDirPath = self.localFs.buildPath(self.backupDirPath, backupDirName)
        try:
            if self.localFs.isExist(backupLocalPath):
                shutil.copytree(backupLocalPath, backupDirPath)
        except Exception, error:
            self._writeLog("Error: can't backup dir: '" + backupLocalPath.encode('utf8') + "' to '" + backupDirPath.encode('utf8') + "'", error)


    def _removeNonExistingDataFromStoredFs(self, storedLocalFsState, localFs):
        for localPath in storedLocalFsState.getAllElements():
            if not localFs.isExist(localPath):
                self._writeLog("Remove info about non-existing record: " + localPath.encode('utf8'))
                if storedLocalFsState.isFile(localPath):
                    storedLocalFsState.deleteFile(localPath)
                else:
                    storedLocalFsState.deleteDir(localPath)


    def _printSyncStat(self, force=False):
        ts = time.time()
        if force or (ts - self.lastFileStatPrintTime > 1):
            self.lastFileStatPrintTime = ts
            print Syncer.WAIT_ANIMATION_CHARS[self.fileStatPrintAnimCounter], "    Dirs: ", self.processedDirsCount, " [", self.updatedDirsCount, "] / Files: ", self.processedFilesCount, " [", self.updatedFilesCount, "]                  \r",

            self.fileStatPrintAnimCounter += 1
            if self.fileStatPrintAnimCounter > len(Syncer.WAIT_ANIMATION_CHARS) - 1:
                self.fileStatPrintAnimCounter = 0
