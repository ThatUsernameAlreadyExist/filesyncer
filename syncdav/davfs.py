from __future__ import with_statement
import socket
import os
import urllib
from tinydav import *
from tinydav.exception import *
from datetime import datetime
from httplib import MULTI_STATUS, OK, CONFLICT, NO_CONTENT, UNAUTHORIZED, CREATED, NOT_FOUND, METHOD_NOT_ALLOWED
from common import PathOperations


class DummyWebDavLock:
    def __enter__(self):
        pass

    def __exit__(self ,type, value, traceback):
        pass


class WebDavElement:
    def __init__(self, rawcontent, response):
        self.isDir = response.get('resourcetype').find('{DAV:}collection') != None
        self.fullPath = urllib.url2pathname(response.href).decode('utf8')

        try:
            # TODO: available variants for last modified:
            # Sun, 06 Nov 1994 08:49:37 GMT  ; RFC 822, updated by RFC 1123
            # Sunday, 06-Nov-94 08:49:37 GMT ; RFC 850, obsoleted by RFC 1036
            # Sun Nov  6 08:49:37 1994       ; ANSI C's asctime() format
            self.lastModifiedTimeGMT = datetime.strptime(self._getElementText(response, 'getlastmodified'), '%a, %d %b %Y %H:%M:%S GMT') # Sat, 06 Jun 2015 16:52:05 GMT
        except Exception:
            self.lastModifiedTimeGMT = None
            pass
        self.etag = self._getElementText(response, 'getetag')
        self.displayName = self._getElementText(response, 'displayname')
        self.contentType = self._getElementText(response, 'getcontenttype')
        try:
            self.size = int(self._getElementText(response, 'getcontentlength', '0'))
        except Exception:
            self.size = 0
            pass


    def _getElementText(self, response, tag, default = ''):
        return response.get(tag).text if tag in response else default


    def __str__(self):
        strRep = "Name: " + self.displayName.encode('utf-8')+ "\n"
        strRep += "Path: " + self.fullPath.encode('utf-8') + "\n"
        strRep += "Dir: " + ("Yes" if self.isDir else "No") + "\n"
        strRep += "Modified: " + (str(self.lastModifiedTimeGMT) if self.lastModifiedTimeGMT is not None else "Unknown" ) + "\n"
        strRep += "Etag: " + self.etag + "\n"
        strRep += "Type: " + self.contentType + "\n"
        strRep += "Size: " + str(self.size) + " bytes\n"

        return strRep


class WebDavFS:
    def __init__(self, server, port, proto, login, password, useLocks):
        socket.setdefaulttimeout(3)    #Set 3 seconds network timeout, because Python 2.5 doesn't have timeout options for network commands.
        self.davClient = WebDAVClient(server, port, proto)
        self.davClient.setbasicauth(login, password)
        self.useLocks = useLocks

    def exists(self, path):
        return len(self._getWebDavElements(path)) > 0


    def isfile(self, path):
        return not self.isdir(path)


    def isdir(self, path):
        elements = self._getWebDavElements(path)
        if len(elements) > 0:
            return elements[0].isDir
        return False


    def list(self, path):
        return self._getWebDavElements(path, 1)


    #Raise exception if download failed.
    #Return file content.
    def download(self, path):
        fileContent = ''
        encodedPath = self._encodePath(path, False)
        lock = self._safeLock(encodedPath)
        if lock != None:
            with lock:
                try:
                    response = self.davClient.get(encodedPath)
                except Exception, error:
                    self._safeUnlock(encodedPath)
                    raise error

            self._safeUnlock(encodedPath)
            if response != OK:
                raise Exception("Download fail " + path.encode('utf-8') + " :" + response.statusline)
            else:
                fileContent = response.content
        else:
            raise Exception("Lock fail on download")
        return fileContent


    #Raise exception if upload failed.
    def upload(self, path, content):
        if content == "":
            content = " " #on some servers we can't create empty files
        encodedPath = self._encodePath(path, False)
        lock = self._safeLock(encodedPath)
        if lock != None:
            with lock:
                try:
                    response = self.davClient.put(encodedPath, content)
                except Exception, error:
                    self._safeUnlock(encodedPath)
                    raise error

            self._safeUnlock(encodedPath)
        else:
            raise Exception("Lock fail on upload")


    def delete(self, path):
        try:
            self.davClient.delete(self._encodePath(path, False))
        except HTTPUserError, error:
            if (error.response != NOT_FOUND):
                raise error
            else:
                pass


    def mkdir(self, path):
        parentDir = os.path.dirname(path)
        encodedParentDirPath = self._encodePath(parentDir)
        lock = self._safeLock(encodedParentDirPath, 10)
        if lock != None:
            with lock:
                try:
                    response = self.davClient.mkcol(self._encodePath(path))
                except HTTPUserError, error:
                    if (error.response != METHOD_NOT_ALLOWED or not self.isdir(path)):
                        self._safeUnlock(encodedParentDirPath)
                        raise error
                    else:
                        pass
                except Exception, error:
                    self._safeUnlock(encodedParentDirPath)
                    raise error

            self._safeUnlock(encodedParentDirPath)
        else:
            raise Exception("Lock fail on mkdir")


    # Return WebDavLockResponse object. Can be used with other requests.
    def _safeLock(self, path, timeoutSec=600):
        if self.useLocks:
            try:
                lock = self.davClient.lock(path, timeout=timeoutSec)
                if lock == OK or lock == CREATED:
                    return lock
            except Exception, err:
                pass
            return None

        return DummyWebDavLock()


    def _safeUnlock(self, path):
        if self.useLocks:
            try:
                self.davClient.unlock(path)
            except:
                pass


    def _getWebDavElements(self, path, depth = 0):
        elements = []
        try:
            responses = self.davClient.propfind(self._encodePath(path), depth, properties = ["resourcetype", "getlastmodified", "getcontentlength"])
            for i in responses:
                webdavElement = WebDavElement(responses.content, i)
                if depth == 0 or not PathOperations.comparePath(webdavElement.fullPath, path): #exclude current path if we list entire folder.
                    elements.append(WebDavElement(responses.content, i))
        except HTTPUserError, error: #on 4xx HTTP status codes
            if error.response != NOT_FOUND:
                raise error
        return elements


    def _encodePath(self, path, addEndSlash=True):
        if not addEndSlash or path.endswith('/'):
            return path.encode('utf8');
        else:
            return (path+'/').encode('utf8')

