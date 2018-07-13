#!/usr/local/bin/python3
# -*- utf-8 -*-
'''
step-1. 载入文件及服务器的配置 ， 若没有，则停止
step-2. 打包本地需要上传的文件及文件夹 ， 若没有，则停止
step-3. 尝试打包本地文件到服务器指定上传目录，若失败，则停止
step-4. ssh远程打包需要替换的文件及文件夹，至文件备份目录，若失败，则停止
step-5，ssh远程删除需要替换的文件及文件夹，若失败，则停止
step-6，ssh远程解压上传的文件及文件夹到被替换的文件及文件夹位置
step-end，退出ssh连接
'''

import json
import os
import tarfile
import time
import paramiko
import select
import re

deployList = []

'''
加载配置文件
'''


def loadConfig():
    global deployList
    print('__________________________________________________________')
    print('_______________________  载入配置  _______________________')
    fDeploy = open('config-list.json', encoding='utf-8')
    _deployList = json.load(fDeploy)
    deployList = reConfigDeployList(_deployList)


'''
    重新配置发布列表，确定哪些需要发布
'''


def reConfigDeployList(_deployList):
    _tmpDeployList = []
    print('_______________________  配置载入完成  _______________________')
    for idx, item in enumerate(_deployList, start=1):
        print('[%d] -  %s \t (%s)' % (idx, item['nameCN'], item['server']['ip']))
    _deployNumStr = input('请输入需要发布的项目对应编号,以空格分割 : ')
    _deployNumArr = re.compile("\ +").split(_deployNumStr)
    for idx, item in enumerate(_deployList, start=1):
        if str(idx) in _deployNumArr:
            _tmpDeployList.append(item)
    return _tmpDeployList


'''
发布文件
'''


def deployFile():
    print('_______________________  发布文件  _______________________')
    for item in deployList:
        itemClientConfig = item['client']
        print('\n\n[start] 准备发布...【%s】- 【%s】' % (item['nameCN'], item['server']['ip']))
        # 先编译项目
        print('[1/8] 编译项目...')
        print("__________________________________________________________")
        print("_______________________  编译项目  _______________________\n")
        # 若编译成功，则进行下一步，否则取消本次发布
        if 0 == os.system(itemClientConfig['buildCmd']):  # 编译成功
            print("\n_______________________  编译完成  _______________________")
            if (os.path.exists(itemClientConfig['path'])):  # 若存在需要打包的目录，则继续
                localMkDir(itemClientConfig['archiveTmpDir'])  # 确保打包目录存在，否则创建目录
                localTarFile = os.path.join(itemClientConfig['archiveTmpDir'],
                                            os.path.basename(itemClientConfig['path'])) + '-' + (
                                       time.strftime('%Y%m%d%H%M%S', time.localtime()) + '.tar')
                print('[2/8] 本地压缩项目...')
                with tarfile.open(localTarFile, 'w') as tar:
                    tar.add(os.path.join(itemClientConfig['path']),
                            arcname=os.path.basename(itemClientConfig['path']))
                print('[finish] 本地压缩结束')
                remotePrepare(item['server'], localTarFile)  # 远程连接方法集合
            else:
                raise Exception(
                    '\n_______________________  压缩失败  _______________________\n[terminal] 取消发布...【%s】- 【%s】' % (
                    item['nameCN'], item['server']['ip']))
        else:
            raise Exception('\n_______________________  编译失败  _______________________\n[terminal] 取消发布...【%s】- 【%s】' % (
                item['nameCN'], item['server']['ip']))


# 远程连接方法集合
def remotePrepare(itemServerConfig, localTarFile):
    print('[3/8] 远程连接...')
    with paramiko.SSHClient() as ssh:
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(itemServerConfig['ip'], 22, itemServerConfig['user'], itemServerConfig['pwd'])
        with paramiko.SFTPClient.from_transport(ssh.get_transport()) as sftp:
            sftp = ssh.open_sftp()
            remoteMkDir(sftp, itemServerConfig['backupDir'])
            remoteMkDir(sftp, itemServerConfig['uploadDir'])
            remoteMkDir(sftp, itemServerConfig['deployDir'])
            remoteTarFile = os.path.join(itemServerConfig['uploadDir'], os.path.basename(localTarFile))
            print('[4/8] 上传文件[' + localTarFile + ']至远程服务器[' + itemServerConfig['uploadDir'], ']')
            sftp.put(localTarFile, remoteTarFile)
            print('[5/8] 备份...')
            remoteBackupOldBean(itemServerConfig, remoteTarFile, ssh, sftp)  # 备份原始文件
            print('[6/8] 清空部署目录...')
            remoteRemoveOldBean(itemServerConfig, sftp)  # 删除原始文件
            print('[7/8] 发布...')
            remoteDeployNewBean(itemServerConfig, remoteTarFile, ssh, sftp)  # 发布新文件
            print('[8/8] 重载服务...')
            remoteServiceReload(itemServerConfig, ssh, sftp)


def remoteServiceReload(itemServerConfig, ssh, sftp):
	# 重载服务暂时未做！
    print('服务重载成功!')


# 远程部署新对象
def remoteDeployNewBean(itemServerConfig, remoteTarFile, ssh, sftp):
    try:
        sftp.stat(remoteTarFile)
        command = 'tar -xvf %s -C %s --strip-components=1' % (remoteTarFile, itemServerConfig['deployDir'])
        remoteExecCommand(ssh, command)
    except IOError:
        print(' - 远程上传文件%s不存在，停止部署' % (remoteTarFile))


# 远程删除原始对象,不删除其目录
def remoteRemoveOldBean(itemServerConfig, sftp):
    remoteRmDir(sftp, itemServerConfig['deployDir'])
    remoteMkDir(sftp, itemServerConfig['deployDir'])


# 远程备份原始对象
def remoteBackupOldBean(itemServerConfig, remoteTarFile, ssh, sftp):
    # 若远程目录，有子文件，则执行备份命令
    files = sftp.listdir(itemServerConfig['deployDir'])
    if (0 < len(files)):  ### 若发布目录，有文件，则执行备份命令
        command = 'cd %s;tar -cvf %s %s' % (os.path.join(itemServerConfig['deployDir'], os.pardir),
                                            os.path.join(itemServerConfig['backupDir'],
                                                         os.path.basename(remoteTarFile)),
                                            os.path.basename(itemServerConfig['deployDir']))
        remoteExecCommand(ssh, command)
    else:
        print(' - 发布目录%s为空' % (itemServerConfig['deployDir']))


# -----------------------------------------
# 私有方法，远程执行命令
# -----------------------------------------
def remoteExecCommand(ssh, command):
    print('  - 执行远程命令 ', command)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(command)
    # Wait for the command to terminate
    while not ssh_stdout.channel.exit_status_ready():
        # Only print data if there is data to read in the channel
        if ssh_stdout.channel.recv_ready():
            rl, wl, xl = select.select([ssh_stdout.channel], [], [], 0.0)
            # if len(rl) > 0:
            #   tmp = ssh_stdout.channel.recv(1024)
            #   output = tmp.decode()
            #   print(output)


def localMkDir(localPath, is_dir=True):
    dirs_ = []
    if is_dir:
        dir_ = localPath
    else:
        dir_, basename = os.path.split(localPath)
    while len(dir_) > 1:
        dirs_.append(dir_)
        dir_, _ = os.path.split(dir_)

    if len(dir_) == 1 and not dir_.startswith("/"):
        dirs_.append(dir_)  # For a remote path like y/x.txt

    while len(dirs_):
        dir_ = dirs_.pop()
        if not os.path.exists(dir_):
            os.mkdir(dir_)


# -----------------------------------------
# 私有方法，远程创建目录
# -----------------------------------------
def remoteMkDir(sftp, remotePath, is_dir=True):
    dirs_ = []
    if is_dir:
        dir_ = remotePath
    else:
        dir_, basename = os.path.split(remotePath)
    while len(dir_) > 1:
        dirs_.append(dir_)
        dir_, _ = os.path.split(dir_)

    if len(dir_) == 1 and not dir_.startswith("/"):
        dirs_.append(dir_)  # For a remote path like y/x.txt

    while len(dirs_):
        dir_ = dirs_.pop()
        try:
            sftp.stat(dir_)
        except:
            sftp.mkdir(dir_)


# -----------------------------------------
# 私有方法，远程删除目录
# -----------------------------------------
def remoteRmDir(sftp, remotePath):
    files = sftp.listdir(remotePath)
    for f in files:
        filepath = os.path.join(remotePath, f)
        try:
            sftp.remove(filepath)
        except IOError:
            remoteRmDir(sftp, filepath)
    sftp.rmdir(remotePath)


'''
主方法
'''
if __name__ == '__main__':
    loadConfig()  # 加载配置文件
    if 0 < len(deployList):
        print('__________________________________________________________\n')
        for item in deployList:
            print('%s\t(%s)' % (item['nameCN'], item['server']['ip']))
        print('\n__________________________________________________________')
        _confirmOk = input('确定发布?[Y/n]  :')
        if '' == _confirmOk or 'y' == _confirmOk.lower():
            deployFile()  # 发布文件
        else:
            print('已取消发布')
    else:
        print('[finish] 未选中项目编号,取消发布')
