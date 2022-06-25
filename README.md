# filesyncer
Sync between local folders, files and WebDAV resources.

Support bidirectional and onedirectional sync (backup), limited file size, multiple folders/targets.
Platform: pythonce 2.5, python 2.5, python 2.7

For manual sync start 'manual.py'
For automatic sync (sync with timeout) start 'auto.py'

#### Configuration
All configuration stored in FileSyncer.ini file.

FileSyncer.ini file structure:

    [MyWebdavBackupTask1 Remote]                - name of sync task with unique id ('Remote')
    Server=webdav.myserver.com                  - webdav server
    Port=443                                    - webdav server port
    Proto=https                                 - connection protocol (http/https)
    ServerSha256=5cc1332c7d4903962a96...        - server ssl sertificate fingerpint (sha256).
                                                  Leave empty if don't need check server certificate validity.
    Username=yourname@myserver.com              - webdav username
    Password=yourpassword                       - webdav password
    MaxFileSizeKB=128                           - maximum size of each file to sync in kilobytes
                                                  (files with greater size will be ignored)
    ReadOnly=1                                  - one direction sync (ReadOnly=1).
                                                  Files in 'MyWebdavBackupTask1 Remote' paths will not be updated/deleted/created
    SyncPaths=sync/New Folder|sync/New File.txt - list of folder or file paths to sync. Delimiter - |
    OnlyIfSyncPathExist=1                       - enable sync only if root sync path exist (set '0' to automatically create non existing path)

    [MyWebdavBackupTask1 Local]                         - name of sync task with unique id ('Remote')
    SyncPaths=C:\sync\Sync Folder|C:\sync\Sync File.txt - list of folder or file paths to sync. Delimiter - |
    OnlyIfSyncPathExist=1

In this config example will be performed sync:

   Task name: MyWebdavBackupTask1
   1) 'sync/New Folder'     -> 'C:\sync\Sync Folder'    (all changed files/folders from 'sync/New Folder' will be copied to 'C:\sync\Sync Folder')
   2) 'sync/New File.txt'   -> 'C:\sync\Sync File.txt'  (file 'sync/New File.txt' will be copied to 'C:\sync\Sync File.txt' if changed)

For folders sync:

    [MyLocalSyncTask1 Remote]
    SyncPaths=C:\Users\Desktop\WebDAV\sync\1|C:\Users\Desktop\WebDAV\sync\11

    [MyLocalSyncTask1 Local]
    SyncPaths=C:\Users\Desktop\WebDAV\sync\2|C:\Users\Desktop\WebDAV\sync\22

In this config example will be performed full sync without limitations.

FileSyncer.ini can contain many sync tasks:

    [MyWebdavBackupTask1 Remote]
    .....
    [MyWebdavBackupTask1 Local]
    .....
    [MyLocalSyncTask1 Remote]
    .....
    [MyLocalSyncTask1 Local]
    .....

Each task must be with unique name.

#### Backup
All backups are stored in 'FileSyncerData\backup' folder.
Before updating/removing local file(folder) while syncing this original file will be copied to backup folder with full date/time prefix.
('1.txt' wiil be copied to '[2015-01-01 12-33-27]1.txt')

#### Sync state
Sync states for all tasks stored in 'FileSyncerData\state' folder.
Remove this folder to start initial sync.

#### Sync log
All sync info stored in FileSyncer.log file.
