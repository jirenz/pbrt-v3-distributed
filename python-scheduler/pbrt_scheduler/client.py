import pickle
import os
import tarfile
import subprocess
import time
import shlex
from pathlib import Path
from argparse import ArgumentParser
import nanolog as nl
from benedict.data_format import load_yaml_file, dump_yaml_str
from pbrt_scheduler.communication import ZmqClient
from pbrt_scheduler.core import MessageType, Message
from pbrt_scheduler.utils import *

logger = nl.Logger.create_logger(
    'client',
    stream='stdout',
    time_format='MD HMS',
    show_level=True,
    # level='debug',
)

_CONFIG = None

def CONFIG():
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_configs()
    return _CONFIG


def load_configs():
    config_path = Path(os.path.expanduser('~/.pbrt-distributed.yml'))
    if not config_path.exists():
        logger.info('Creating default config at {}'.format(str(config_path)))
        with config_path.open('w') as f:
            f.write(dump_yaml_str({
                'local_temp_tar': '/tmp/pbrt-distributed.tar.gz',
                'server_host': '127.0.0.1',
                'server_port': 13480,
            }))
            f.write('# The default number of workers for each render\n')
            f.write('# num_workers: 2\n')
            f.write('# Host of the server that `client render` can scp to\n')
            f.write('# fs_host: file_system\n')
            f.write('# Path for saving the file\n')
            f.write('# fs_save_path\n')
            f.write('# Path for reading the file\n')
            f.write('# fs_read_path\n')
    config = load_yaml_file(str(config_path))
    if 'local_temp_tar' not in config:
        config['local_temp_tar'] = '/tmp/pbrt-distributed.tar.gz'
    if 'server_host' not in config:
        config['server_host'] = '127.0.0.1'
    if 'server_port' not in config:
        config['server_port'] = 13480
    config['server_add'] = '{}:{}'.format(config['server_host'], config['server_port'])
    return config

# TODO: load config
def get_backend():
    address = CONFIG()['server_add']
    return ZmqClient(address=address, serializer=pickle.dumps, deserializer=pickle.loads)

def handle_backend_query_msg(resp):
    if resp.type == MessageType.error:
        logger.error(resp.data['reason'])
        raise ValueError(resp.data['reason'])

def get_jobs():
    msg = Message(MessageType.api_query_jobs, {})
    backend_client = get_backend()
    resp = backend_client.request(msg)
    handle_backend_query_msg(resp)
    nl.pp(resp.data)
    # TODO: print out

def get_job(job_name):
    di = {'job_name': job_name}
    msg = Message(MessageType.api_query_job, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    handle_backend_query_msg(resp)
    nl.pp(resp.data)
    # TODO: print out

def get_workers():
    msg = Message(MessageType.api_query_workers, {})
    backend_client = get_backend()
    resp = backend_client.request(msg)
    handle_backend_query_msg(resp)
    nl.pp(resp.data)

def create_job(context_name, context_folder, pbrt_file, num_workers):
    di = {
        'context_name': context_name,
        'context_folder': context_folder,
        'pbrt_file': pbrt_file,
        'num_workers': num_workers,
    }
    logger.info('Creating job {}'.format(context_name))
    nl.pp(di)
    msg = Message(MessageType.api_assign_job, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    handle_backend_query_msg(resp)
    nl.pp(resp.data)

def delete_job(job_name):
    di = {'job_name': job_name}
    msg = Message(MessageType.api_delete_job, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    handle_backend_query_msg(resp)
    logger.info('Success')

### Commandline interface

def job(args):
    if args.job_name:
        get_job(args.job_name)
    else:
        get_jobs()

def worker(args):
    get_workers()

def delete(args):
    delete_job(args.job_name)

def create(args):
    create_job(args.job_name, args.job_folder, args.pbrt_file, args.num_workers)

def _find_pbrt_file(pbrt_file):
    pbrt_file = Path(pbrt_file).expanduser().resolve()
    if not pbrt_file.exists():
        raise ValueError('Cannot find pbrt file {}'.format(pbrt_file))
    logger.infofmt('Found pbrt file: {}', str(pbrt_file))
    return pbrt_file

def get_config_for_nfs():
    """
    Does error checking
    """
    config = CONFIG()
    for key in ['num_workers', 'fs_host', 'fs_save_path', 'fs_read_path']:
        if not key in config:
            raise ValueError('Missing key {} in config'.format(key))
    return config

def run_command(args):
    logger.infofmt('$> {}', ' '.join(args))
    subprocess.run(args, check=True)

def render(args):
    config = get_config_for_nfs()

    pbrt_file = _find_pbrt_file(args.pbrt_file)

    if args.job_name is not None:
        job_name = args.job_name
        args.folder_name if args.folder_name is not None else job_name
    else:
        job_name, folder_name = pbrt_file.stem, pbrt_file.parent.stem
    logger.infofmt('Job name: {}', job_name)

    if args.num_workers is None:
        num_workers = config['num_workers']
    else:
        num_workers = args.num_workers
    logger.infofmt('Max workers: {}', num_workers)

    local_context_folder = pbrt_file.parent

    remote_save_root = Path(config['fs_save_path'])
    context_folder = remote_save_root / folder_name

    logger.info('Decompressing file on remote')
    chmod_subcommand = ' '.join(['chmod', '666', str(local_context_folder / '*.exr')])
    args_local_chmod = ['/bin/bash', '-c', chmod_subcommand]
    args_mkdirp = ['ssh', config['fs_host'], 'mkdir', '-p', str(context_folder)]
    # TODO: fix exclude
    args_rsync = ['rsync', '-rvztp', '--progress', str(local_context_folder) + '/', config['fs_host'] + ':' + str(context_folder)]
    args_chmod = ['ssh', config['fs_host'], 'chmod', '777', str(context_folder)] 
    run_command(args_local_chmod)
    run_command(args_mkdirp)
    run_command(args_rsync)
    run_command(args_chmod)

    remote_read_root = Path(config['fs_read_path'])
    context_read_folder = remote_read_root / folder_name
    remote_read_pbrt_file = context_read_folder / pbrt_file.name

    create_job(job_name, str(context_read_folder), str(remote_read_pbrt_file), num_workers)

def fetch(args):
    config = get_config_for_nfs()
    if args.remote_context_folder is None:
        args.remote_context_folder = Path('.').resolve().stem
    remote_context_folder = Path(config['fs_save_path']) / args.remote_context_folder
    local_context_folder = args.local_context_folder if args.local_context_folder else '.'
    local_context_folder = Path(local_context_folder).expanduser().resolve()
    while True:

        if args.all_files:
            args_rsync = ['rsync', '-ruvztp', '--progress', 
                          config['fs_host'] + ':' + str(remote_context_folder),
                          str(local_context_folder)]
            run_command(args_rsync)
        else:
            # get exrs
            args_rsync1 = ['rsync', '-uztp', '--exclude="*"', "--include='*.exr'",
                           config['fs_host'] + ':' + str(remote_context_folder) + '/*',
                           str(local_context_folder) + '/']
            run_command(args_rsync1)
            # get logs
            args_rsync2 = ['rsync', '-ruztp', "--include='*.txt'", "--exclude='*'",
                           config['fs_host'] + ':' + str(remote_context_folder) + '/',
                           str(local_context_folder) + '/']
            run_command(args_rsync2)
        if args.no_repeat:
            break
        else:
            countdown(args.repeat_interval, 'Resyncing in {:3}s')
            print('=' * 20)


def _setup_job(subparsers):
    job_parser = subparsers.add_parser(
        'job',
        help='list all jobs or one job',
        aliases=['j'],
    )
    job_parser.add_argument('job_name', nargs='?', default=None)
    job_parser.set_defaults(func=job)

def _setup_delete(subparsers):
    delete_parser = subparsers.add_parser(
        'delete-job',
        help='delete one job',
        aliases=['d'],
    )
    delete_parser.add_argument('job_name')
    delete_parser.set_defaults(func=delete)

def _setup_workers(subparsers):
    worker_parser = subparsers.add_parser(
        'worker',
        help='list all workers',
        aliases=['w'],
    )
    worker_parser.set_defaults(func=worker)

def _setup_create(subparsers):
    create_parser = subparsers.add_parser(
        'create',
        help='create a rendering task',
        aliases=['c'],
    )
    create_parser.add_argument('job_name', type=str)
    create_parser.add_argument('job_folder', type=str)
    create_parser.add_argument('pbrt_file', type=str)
    create_parser.add_argument('num_workers', type=int)
    create_parser.set_defaults(func=create)

def _setup_render(subparsers):
    render_parser = subparsers.add_parser(
        'render',
        help='deploy local scene onto the cloud and render',
        aliases=['r']
    )
    render_parser.add_argument('pbrt_file', type=str, help='pbrt_file to render')
    render_parser.add_argument('job_name', type=str, nargs='?', default=None,
                               help='name of rendering job')
    render_parser.add_argument('folder_name', type=str, nargs='?', default=None,
                               help='name of containing folder rendering job')
    render_parser.add_argument('--num-workers', default=None, type=int,
                               help='number of workers to use')
    render_parser.set_defaults(func=render)

def _setup_fetch(subparsers):
    fetch_parser = subparsers.add_parser(
        'fetch',
        help='fetch data on remote',
        aliases=['f']
    )
    fetch_parser.add_argument('remote_context_folder', type=str, nargs='?', default=None, help='remote folder name of job')
    fetch_parser.add_argument('local_context_folder', type=str, nargs='?', default=None, help='local folder to sync to')
    fetch_parser.add_argument('--all-files', action='store_true')
    fetch_parser.add_argument('-n', '--no-repeat', action='store_true', help='keep fetching')
    fetch_parser.add_argument('--repeat-interval', type=int, default=15, help='fetch every repeat_interval seconds')
    fetch_parser.set_defaults(func=fetch)


def main():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(
        help='action commands',
        dest='action'  # will store to parser.subcommand_name
    )
    subparsers.required = True

    _setup_job(subparsers)
    _setup_workers(subparsers)
    _setup_create(subparsers)
    _setup_delete(subparsers)
    _setup_render(subparsers)
    _setup_fetch(subparsers)

    args = parser.parse_args()
    args.func(args)

if __name__ == '__main__':
    main()
