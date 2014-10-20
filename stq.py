#!env python
# Copyright (c) 2014, Stephan Rave
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import print_function

import argparse
import atexit
import os
import signal
import socket
import stat
import subprocess
import time


parser = argparse.ArgumentParser()
parser.add_argument('QUEUE_DIRECTORY')
args = parser.parse_args()

path = os.path.abspath(os.path.expanduser(args.QUEUE_DIRECTORY))
queue_path = os.path.join(path, 'QUEUE')
running_path = os.path.join(path, 'RUNNING')
failed_path = os.path.join(path, 'FAILED')
finished_path = os.path.join(path, 'FINISHED')
pids_path = os.path.join(path, 'PIDS')
pid_file = os.path.join(pids_path, '{}-{}'.format(socket.gethostname(), os.getpid()))


# create queue directory structure
if not os.path.exists(path):
    os.mkdir(path)
for p in [queue_path, running_path, failed_path, finished_path, pids_path]:
    if not os.path.exists(p):
        os.mkdir(p)


# create pid file and ensure it is removed at program exit
open(pid_file, 'w').close()
def cleanup():
    os.unlink(pid_file)
atexit.register(cleanup)
def sig_handler(*args):
    exit()
signal.signal(signal.SIGTERM, sig_handler)


# main loop
waiting = False
while True:

    # look for new jobs
    files = os.listdir(queue_path)
    if not files:
        if not waiting:
            print('NO NEW TASKS FOUND, WAITING ...')
            waiting = True
        time.sleep(10)
        continue
    waiting = False

    # select oldest job for processing
    script_name = min((os.path.getmtime(os.path.join(queue_path, f)), f) for f in files)[1]

    # create working directory and move job to this directory
    work_path = os.path.join(running_path, '{}-{}-{}'.format(socket.gethostname(), os.getpid(), script_name))
    os.mkdir(work_path)
    try:
        os.rename(os.path.join(queue_path, script_name),
                  os.path.join(work_path, script_name))
    except OSError:  # might happen if different worker selects script at the same time
        print('FAILED TO SETUP ' + script_name)
        time.sleep(1)
        os.rmdir(work_path)
        continue

    # run the job
    print('\n\n******** LAUNCHING ' + script_name + ' ********\n\n')
    script_path = os.path.join(work_path, script_name)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)
    # we use stdbuf -o000 to deactivate stdout stderr buffering s.t. output is in the right order
    successful = subprocess.call('stdbuf -o000 ' + script_path + ' 2>&1 | tee out.txt',
                                 cwd=work_path, shell=True) == 0

    # move working directory to FINISHED resp. FAILED
    dst_dir = script_name
    dst_dir_counter = 1
    while True:
        dst_path = os.path.join(finished_path if successful else failed_path, dst_dir)
        try:
            os.rename(work_path, dst_path)
            break
        except OSError:
            if not os.path.exists(dst_path):
                raise IOError('Something went wrong!')
            dst_dir_counter += 1
            dst_dir = '{}_{}'.format(script_name, dst_dir_counter)
