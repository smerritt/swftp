"""
This file contains the primary server code for the FTP server.

See COPYING for license information.
"""
from zope.interface import implements
from twisted.cred import portal
from twisted.protocols.ftp import IFTPShell, IReadFile, IWriteFile, \
    FileNotFoundError, CmdNotImplementedForArgError, IsNotADirectoryError, \
    IsADirectoryError
from twisted.internet import defer
from twisted.internet.protocol import Protocol
import stat

from swftp.swiftfilesystem import SwiftFileSystem, swift_stat
from swftp.swift import NotFound, Conflict


class SwiftFTPRealm:
    implements(portal.IRealm)

    def getHomeDirectory(self):
        return '/'

    def requestAvatar(self, avatarId, mind, *interfaces):
        return interfaces[0], SwiftFTPShell(avatarId), lambda: None


def stat_format(keys, props):
    st = swift_stat(**props)
    l = []
    for key in keys:
        if key == 'size':
            val = st.st_size
        elif key == 'directory':
            val = st.st_mode & stat.S_IFDIR == stat.S_IFDIR
        elif key == 'permissions':
            val = val = st.st_mode
        elif key == 'hardlinks':
            val = 0
        elif key == 'modified':
            val = int(st.st_mtime)
        elif key in 'owner':
            val = 'nobody'
        elif key in 'group':
            val = 'nobody'
        else:  # Unknown Value
            val = ''
        l.append(val)
    return l


class SwiftFTPShell:
    """ Implements all the methods needed to treat Swift as an FTP Shell """
    implements(IFTPShell)

    def __init__(self, swiftconn):
        self.swiftconn = swiftconn
        self.swiftfilesystem = SwiftFileSystem(self.swiftconn)

    def _fullpath(self, path_parts):
        return '/'.join(path_parts)

    def makeDirectory(self, path):
        fullpath = self._fullpath(path)
        return self.swiftfilesystem.makeDirectory(fullpath)

    def removeDirectory(self, path):
        fullpath = self._fullpath(path)

        def errback(failure):
            failure.trap(NotFound)
        d = self.swiftfilesystem.removeDirectory(fullpath)
        d.addErrback(errback)
        return d

    def removeFile(self, path):
        fullpath = self._fullpath(path)

        def errback(failure):
            failure.trap(NotFound)
        d = self.swiftfilesystem.removeFile(fullpath)
        d.addErrback(errback)
        return d

    def rename(self, fromPath, toPath):
        oldpath = self._fullpath(fromPath)
        newpath = self._fullpath(toPath)

        d = self.swiftfilesystem.renameFile(oldpath, newpath)

        def errback(failure):
            failure.trap(NotFound, Conflict, NotImplementedError)
            if failure.check(NotFound):
                return defer.fail(FileNotFoundError(oldpath))
            else:
                return defer.fail(CmdNotImplementedForArgError(oldpath))
        d.addErrback(errback)
        return d

    def access(self, path):
        fullpath = self._fullpath(path)

        def cb(result):
            if result['content_type'] == 'application/directory':
                return defer.succeed(lambda: None)
            return defer.fail(IsNotADirectoryError(path))

        def err(failure):
            failure.trap(NotFound)
            return defer.succeed(lambda: None)

        d = self.swiftfilesystem.getAttrs(fullpath)
        d.addCallback(cb)
        d.addErrback(err)
        return d

    def stat(self, path, keys=()):
        fullpath = self._fullpath(path)

        def cb(result):
            return stat_format(keys, result)

        def err(failure):
            failure.trap(NotFound)
            return defer.fail(FileNotFoundError(path))

        d = self.swiftfilesystem.getAttrs(fullpath)
        d.addCallback(cb)
        d.addErrback(err)
        return d

    def list(self, path=None, keys=()):
        fullpath = self._fullpath(path)

        def cb(results):
            l = []
            for key, value in results.iteritems():
                l.append([key, stat_format(keys, value)])
            return l

        d = self.swiftfilesystem.get_full_listing(fullpath)
        d.addCallback(cb)
        return d

    def openForReading(self, path):
        fullpath = self._fullpath(path)

        def cb(results):
            return SwiftReadFile(self.swiftfilesystem, fullpath)
        try:
            d = self.swiftfilesystem.checkFileExistance(fullpath)
            d.addCallback(cb)
            return d
        except NotImplementedError:
            return defer.fail(IsADirectoryError(path))

    def openForWriting(self, path):
        fullpath = self._fullpath(path)
        f = SwiftWriteFile(self.swiftfilesystem, fullpath)
        return defer.succeed(f)


class SwiftWriteFile:
    implements(IWriteFile)

    def __init__(self, swiftfilesystem, fullpath):
        self.swiftfilesystem = swiftfilesystem
        self.fullpath = fullpath
        self.finished = None

    def receive(self):
        d, writer = self.swiftfilesystem.startFileUpload(self.fullpath)
        self.finished = d
        return defer.succeed(writer)

    def close(self):
        return self.finished


class SwiftReadFile(Protocol):
    implements(IReadFile)

    def __init__(self, swiftfilesystem, fullpath):
        self.swiftfilesystem = swiftfilesystem
        self.fullpath = fullpath
        self.finished = defer.Deferred()

    def cb_send(self, result):
        return self.finished

    def send(self, consumer):
        self.consumer = consumer
        d = self.swiftfilesystem.startFileDownload(self.fullpath, self)
        d.addCallback(self.cb_send)
        return d

    def dataReceived(self, data):
        self.consumer.write(data)

    def connectionLost(self, reason):
        from twisted.web._newclient import ResponseDone
        from twisted.web.http import PotentialDataLoss

        if reason.check(ResponseDone) or reason.check(PotentialDataLoss):
            self.finished.callback(None)
        else:
            self.finished.errback(reason)
        self.consumer.stopProducing()

    def makeConnection(self, transport):
        pass

    def connectionMade(self):
        pass