#!/usr/bin/python3
import os
import sys
import shlex
import shutil


BUCKET_URL = os.environ['BUCKET_URL']
# "s3://cloudrt-jz/island_pbrt"
RESULT_FILE_PATH = os.environ['RESULT_FILE_PATH']
# "s3://cloudrt-result/results-64x48"


def download(bucket_url):
    os.system('mkdir -p /fs/cloudrt')
    os.system('aws s3 cp {} - | tar xz -C /fs/cloudrt --strip-components=1'.format(bucket_url))
    os.chdir('/fs/cloudrt/pbrt')


def _run_cmd_list(args):
    print('args')
    print(args)
    if len(args) == 1:
        os.system(args[0])
    else:  # docker run
        os.system(' '.join(args))


def upload(result_file_path):
    os.system('aws s3 cp --recursive --exclude "*" --include "*.txt" --include "*.png" --exclude "*/*" ./ {}'.format(result_file_path))


if __name__ == "__main__":
    download(BUCKET_URL)
    _run_cmd_list(sys.argv[1:])
    upload(RESULT_FILE_PATH)
