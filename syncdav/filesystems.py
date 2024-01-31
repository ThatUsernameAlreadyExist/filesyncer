from __future__ import with_statement
import os, sys, shutil, datetime, pickle, hashlib
from stat import *
import davfs
from common import PathOperations

class FileSystemElement:
    def __init__(self, parentPath, name, isDir, lastModifiedTimeGMT, size, isLocked = False):
        self.parentPath = parentPath
        self.name = name
        self.isDir = isDir
        self.lastModifiedTimeGMT = lastModifiedTimeGMT
        self.size = size
        self.isLocked = isLocked

    def __hash__(self):
        return hash((self.name, self.parentPath))

    def __eq__(self, other):
        return self.name == other.name
#end class FileSystemElement


class LocalFileSystem:
    def isReadOnly(self):
        return False


    def list(self, dirPath):
        elementList = [];
        for element in os.listdir(dirPath):
            pathname = os.path.join(dirPath, element)
            try:
                elementList.append(self.getFileSystemElement(pathname))
            except Exception, error:
                elementList.append(FileSystemElement(os.path.dirname(pathname), os.path.basename(pathname), False, datetime.datetime.utcnow(), 0, True))
        return elementList


    def getFileSystemElement(self, path):
        statResult = os.stat(path)
        timestamp = statResult.st_mtime if statResult.st_mtime > statResult.st_ctime else statResult.st_ctime
        return FileSystemElement(os.path.dirname(path), os.path.basename(path), S_ISDIR(statResult.st_mode), datetime.datetime.utcfromtimestamp(timestamp), statResult.st_size)


    def writeFile(self, filePath, content):
        if content != None:
            try:
                with open(filePath, "wb") as file:
                    file.write(content)
            except IOError, error:
                strError = str(error)

                # If permission denied on Windows might be trying to update a
                # hidden file, in which case try opening without CREATE
                # See: https://stackoverflow.com/questions/13215716/ioerror-errno-13-permission-denied-when-trying-to-open-hidden-file-in-w-mod
                if "Errno 13" in strError or "Permission" in strError:
                    with open(filePath, "r+b") as file:
                        file.truncate(0)
                        file.write(content)
                else:
                    raise error


    def readFile(self, filePath):
        with open(filePath, "rb") as file:
            return file.read()


    def deleteFile(self, filePath):
        os.remove(filePath)


    def createDir(self, dirPath):
        os.makedirs(dirPath)


    def deleteDir(self, dirPath):
        if os.path.isdir(dirPath):
            shutil.rmtree(dirPath)


    def isFile(self, path):
        return os.path.isfile(path)


    def isExist(self, path):
        return os.path.exists(path)


    def buildPath(self, folder, file):
        return os.path.join(folder, file)
#end class LocalFileSystem


class WebDavFileSystem:
    def __init__(self, server, port, proto, login, password, useLocks):
        self.dav = davfs.WebDavFS(server, port, proto, login, password, useLocks)


    def isReadOnly(self):
        return False


    def list(self, dirPath):
        elementList = [];
        for element in self.dav.list(dirPath):
            elementList.append(FileSystemElement(dirPath, PathOperations.getPathLastElement(element.fullPath), element.isDir, element.lastModifiedTimeGMT, element.size))
        return elementList


    def getFileSystemElement(self, path):
        elements = self.dav._getWebDavElements(path)
        if len(elements) > 0:
            element = elements[0]
            return FileSystemElement(path, PathOperations.getPathLastElement(path), element.isDir, element.lastModifiedTimeGMT, element.size)
        return None


    def writeFile(self, filePath, content):
        self.dav.upload(filePath, content)


    def readFile(self, filePath):
        return self.dav.download(filePath)


    def deleteFile(self, filePath):
        self.dav.delete(filePath)


    def createDir(self, dirPath):
        self.dav.mkdir(dirPath)


    def deleteDir(self, dirPath):
        self.deleteFile(dirPath)


    def isFile(self, path):
        return self.dav.isfile(path)


    def isExist(self, path):
        return self.dav.exists(path)


    def buildPath(self, folder, file):
        return folder + "/" + file
#end class WebDavFileSystem


class StoredFileSystem:
    def __init__(self, remoteSyncPath, localSyncPath, settingsDirPath):
        self.localFilesystem = LocalFileSystem();
        if not self.localFilesystem.isExist(settingsDirPath):
            self.localFilesystem.createDir(settingsDirPath)
        self.storedFilePath = \
            os.path.join(settingsDirPath, \
            hashlib.sha224(localSyncPath.encode('utf8') + remoteSyncPath.encode('utf8')).hexdigest()).decode('utf8')

        self.storedPaths = {}
        self._loadFromFile()


    def getAllElements(self):
        allElements = []
        for key in self.storedPaths:
            allElements.append(key.decode('utf8'))
        return allElements


    def isReadOnly(self):
        return False


    def getFileSystemElement(self, path):
        encodedPath = path.encode('utf8')
        if encodedPath in self.storedPaths:
            return self.storedPaths[encodedPath]
        else:
            return None


    def writeFile(self, filePath, content):
        self.storedPaths[filePath.encode('utf8')] =\
            FileSystemElement(filePath, os.path.dirname(filePath), False, self._getCurrentStoreUTC(), len(content))
        self._storeInFile()


    def deleteFile(self, filePath):
        encodedPath = filePath.encode('utf8')
        if encodedPath in self.storedPaths:
            del self.storedPaths[encodedPath]
            self._storeInFile()


    def createDir(self, dirPath):
        self.storedPaths[dirPath.encode('utf8')] =\
            FileSystemElement(dirPath, os.path.dirname(dirPath), True, self._getCurrentStoreUTC(), 0)
        self._storeInFile()


    def deleteDir(self, dirPath):
        encodedPath = dirPath.encode('utf8')
        for key in self.storedPaths.keys():
            if key == encodedPath or PathOperations.isSubPath(encodedPath, key):
                del self.storedPaths[key]
        self._storeInFile()


    def isFile(self, path):
        encodedPath = path.encode('utf8')
        return (encodedPath in self.storedPaths) and not self.storedPaths[encodedPath].isDir


    def isExist(self, path):
        return path.encode('utf8') in self.storedPaths


    def _loadFromFile(self):
        if self.localFilesystem.isFile(self.storedFilePath):
            with open(self.storedFilePath, "rb") as file:
                self.storedPaths = pickle.load(file)


    def _storeInFile(self):
        with open(self.storedFilePath, "wb") as file:
            pickle.dump(self.storedPaths, file)


    def _getCurrentStoreUTC(self):
        return datetime.datetime.utcnow() + datetime.timedelta(seconds=10) #add 10 seconds to prevent differences between file time calculation
#end class StoredFileSystem


class ReadOnlyFileSystem:
    def __init__(self, filesystem):
        self.filesystem = filesystem


    def isReadOnly(self):
        return True


    def list(self, dirPath):
        return self.filesystem.list(dirPath)


    def getFileSystemElement(self, path):
        return self.filesystem.getFileSystemElement(path)


    def writeFile(self, filePath, content):
        pass


    def readFile(self, filePath):
        return self.filesystem.readFile(filePath)


    def deleteFile(self, filePath):
        pass


    def createDir(self, dirPath):
        pass


    def deleteDir(self, dirPath):
        pass


    def isFile(self, path):
        return self.filesystem.isFile(path)


    def isExist(self, path):
        return self.filesystem.isExist(path)


    def buildPath(self, folder, file):
        return self.filesystem.buildPath(folder, file)
#end class ReadOnlyFileSystem