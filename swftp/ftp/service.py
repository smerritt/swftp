"""
This file defines what is required for swftp-ftp to work with twistd.

See COPYING for license information.
"""
from twisted.application import internet
from twisted.python import usage
from twisted.internet import reactor

import ConfigParser
import signal
import os


def get_config(config_path, overrides):
    defaults = {
        'auth_url': 'http://127.0.0.1:8080/auth/v1.0',
        'host': '0.0.0.0',
        'port': '5021',
        'num_persistent_connections': '4',
        'connection_timeout': '240',
        'welcome_message': 'Welcome to SwFTP'
                           ' - an FTP interface for Openstack Swift',
    }
    c = ConfigParser.ConfigParser(defaults)
    c.add_section('ftp')
    c.read([config_path, '/etc/swift/swftp.conf',
           os.path.expanduser('~/.swftp.cfg')])
    for k, v in overrides.iteritems():
        if v:
            c.set('ftp', k, v)
    return c


class Options(usage.Options):
    "Defines Command-line options for the swftp-ftp service"
    optFlags = []
    optParameters = [
        ["config_file", "c", "/etc/swift/swftp.conf",
            "Location of the swftp config file."],
        ["auth_url", "a", None,
            "Auth Url to use. Defaults to the config file value if it exists. "
            "[default: http://127.0.0.1:8080/auth/v1.0]"],
        ["port", "p", None, "Port to bind to."],
        ["host", "h", None, "IP to bind to."],
    ]


def makeService(options):
    """
    Makes a new swift- ftp service. The only option is the config file
    location. The config file has the following options:
     - host
     - port
     - auth_url
     - num_persistent_connections
     - connection_timeout
     - welcome_message
    """
    from twisted.protocols.ftp import FTPFactory
    from twisted.web.client import HTTPConnectionPool
    from twisted.cred.portal import Portal

    from swftp.ftp.server import SwiftFTPRealm
    from swftp.auth import SwiftBasedAuthDB
    from swftp.utils import print_runtime_info

    c = get_config(options['config_file'], options)

    pool = HTTPConnectionPool(reactor, persistent=True)
    pool.maxPersistentPerHost = c.getint('ftp', 'num_persistent_connections')
    pool.cachedConnectionTimeout = c.getint('ftp', 'connection_timeout')

    authdb = SwiftBasedAuthDB(auth_url=c.get('ftp', 'auth_url'), pool=pool)

    ftpportal = Portal(SwiftFTPRealm())
    ftpportal.registerChecker(authdb)
    ftpfactory = FTPFactory(ftpportal)
    ftpfactory.welcomeMessage = c.get('ftp', 'welcome_message')
    ftpfactory.allowAnonymous = False

    signal.signal(signal.SIGUSR1, print_runtime_info)
    signal.signal(signal.SIGUSR2, print_runtime_info)

    return internet.TCPServer(c.getint('sftp', 'port'), ftpfactory,
                              interface=c.get('ftp', 'host'))